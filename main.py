import numpy as np
import py_gpmf_parser as pgfp
from pathlib import Path
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import subprocess
import re


class GoProTelemetryExtractor:
    def __init__(self, mp4_filepath):
        self.mp4_filepath = mp4_filepath
        self.handle = None

    def open_source(self):
        if self.handle is None:
            self.handle = pgfp.OpenMP4Source(
                self.mp4_filepath, 
                pgfp.MOV_GPMF_TRAK_TYPE, 
                pgfp.MOV_GPMF_TRAK_SUBTYPE, 
                0
            )
        else:
            raise ValueError("Source is already opened!")

    def close_source(self):
        if self.handle is not None:
            pgfp.CloseSource(self.handle)
            self.handle = None
        else:
            raise ValueError("No source to close!")

    def get_image_timestamps_s(self):
        if self.handle is None:
            raise ValueError("Source is not opened!")
        num_frames, numer, denom = pgfp.GetVideoFrameRateAndCount(self.handle)
        frametime = denom / numer
        timestamps = []
        for i in range(num_frames):
            timestamps.append(i * frametime)
        return np.array(timestamps)

    def extract_data(self, sensor_type):
        if self.handle is None:
            raise ValueError("Source is not opened!")
        
        results = []
        timestamps = []
        
        rate, start, end = pgfp.GetGPMFSampleRate(
            self.handle, 
            pgfp.Str2FourCC(sensor_type), 
            pgfp.Str2FourCC("SHUT")
        )
        
        num_payloads = pgfp.GetNumberPayloads(self.handle)
        
        for i in range(num_payloads):
            payloadsize = pgfp.GetPayloadSize(self.handle, i)
            res_handle = 0
            res_handle = pgfp.GetPayloadResource(self.handle, res_handle, payloadsize)
            payload = pgfp.GetPayload(self.handle, res_handle, i, payloadsize)
            
            ret, t_in, t_out = pgfp.GetPayloadTime(self.handle, i)
            delta_t = t_out - t_in
            
            ret, stream = pgfp.GPMF_Init(payload, payloadsize)
            if ret != pgfp.GPMF_ERROR.GPMF_OK:
                continue
            
            while pgfp.GPMF_ERROR.GPMF_OK == pgfp.GPMF_FindNext(
                stream, 
                pgfp.Str2FourCC("STRM"), 
                pgfp.GPMF_RECURSE_LEVELS_AND_TOLERANT
            ):
                if pgfp.GPMF_ERROR.GPMF_OK != pgfp.GPMF_FindNext(
                    stream, 
                    pgfp.Str2FourCC(sensor_type), 
                    pgfp.GPMF_RECURSE_LEVELS_AND_TOLERANT
                ):
                    continue
                
                samples = pgfp.GPMF_Repeat(stream)
                elements = pgfp.GPMF_ElementsInStruct(stream)
                
                if samples:
                    buffersize = samples * elements * 8
                    ret, data = pgfp.GPMF_ScaledData(
                        stream, 
                        buffersize, 
                        0, 
                        samples, 
                        pgfp.GPMF_SampleType.DOUBLE
                    )
                    data = data[:samples * elements]
                    
                    if pgfp.GPMF_ERROR.GPMF_OK == ret:
                        results.extend(np.reshape(data, (-1, elements)))
                        timestamps.extend([t_in + j * delta_t / samples for j in range(samples)])
            
            pgfp.GPMF_ResetState(stream)
        
        return np.array(results), np.array(timestamps) + start

    def close(self):
        self.close_source()


def get_video_creation_time(video_file):
    try:
        cmd = ["exiftool", "-CreateDate", "-DateTimeOriginal", "-MediaCreateDate", "-s3", str(video_file)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if line:
                line = line.replace('+00:00', 'Z')
                
                for fmt in ["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y:%m:%d %H:%M:%S"]:
                    try:
                        return datetime.strptime(line.replace('Z', '+0000'), fmt.replace('Z', '%z'))
                    except:
                        continue
        
        print(f"  Warning: Could not parse creation time, using current time")
        return datetime.utcnow()
    except Exception as e:
        print(f"  Warning: exiftool error ({e}), using current time")
        return datetime.utcnow()


def normalize_gps_to_1hz(gps_data, timestamps):
    if len(gps_data) == 0:
        return [], []
    
    t_start = timestamps[0]
    t_end = timestamps[-1]
    duration = int(np.ceil(t_end - t_start))
    
    target_times = np.arange(0, duration + 1, 1.0)
    
    normalized_gps = []
    normalized_times = []
    
    for target_t in target_times:
        idx = np.argmin(np.abs(timestamps - (t_start + target_t)))
        
        normalized_gps.append(gps_data[idx])
        normalized_times.append(target_t)
    
    return np.array(normalized_gps), np.array(normalized_times)


def write_gpx_with_extensions(gps_data, timestamps, output_file, name, creation_time):
    if len(gps_data) == 0:
        return False
    
    gps_data_1hz, timestamps_1hz = normalize_gps_to_1hz(gps_data, timestamps)
    
    ns_gpx = "http://www.topografix.com/GPX/1/1"
    
    ET.register_namespace('', ns_gpx)
    
    gpx = ET.Element("gpx", version="1.1", creator="Harsh Mand")
    gpx.set("xmlns", ns_gpx)
    
    metadata = ET.SubElement(gpx, "metadata")
    ET.SubElement(metadata, "name").text = f"GPS Logger {creation_time.strftime('%Y%m%d-%H%M%S')}"
    ET.SubElement(metadata, "desc").text = name
    ET.SubElement(metadata, "time").text = creation_time.strftime('%Y-%m-%dT%H:%M:%SZ')
    
    trk = ET.SubElement(gpx, "trk")
    ET.SubElement(trk, "name").text = f"Track {creation_time.strftime('%Y%m%d-%H%M%S')}"
    ET.SubElement(trk, "type").text = "running"
    trkseg = ET.SubElement(trk, "trkseg")
    
    for i, (gps, ts) in enumerate(zip(gps_data_1hz, timestamps_1hz)):
        if len(gps) >= 9:
            lat = gps[0]
            lon = gps[1]
            alt = gps[2]
            speed_2d = gps[3]
            speed_3d = gps[4]
            dop = gps[7]
            fix = int(gps[8])
            
            sat = 8 if fix == 3 else 4
            
            if abs(lat) <= 90 and abs(lon) <= 180:
                trkpt = ET.SubElement(trkseg, "trkpt", lat=f"{lat:.7f}", lon=f"{lon:.7f}")
                ET.SubElement(trkpt, "ele").text = f"{alt:.3f}"
                
                point_time = creation_time + timedelta(seconds=int(ts))
                ET.SubElement(trkpt, "time").text = point_time.strftime('%Y-%m-%dT%H:%M:%SZ')
                ET.SubElement(trkpt, "speed").text = f"{speed_2d:.3f}"
                ET.SubElement(trkpt, "sat").text = str(sat)
    
    tree = ET.ElementTree(gpx)
    ET.indent(tree, space="  ")
    tree.write(output_file, encoding="utf-8", xml_declaration=True)
    return True

def extract_all_gps(folder="ip"):
    folder_path = Path(folder)
    video_files = sorted(
        list(folder_path.glob("*.360")) + list(folder_path.glob("*.mp4"))
    )
    
    if not video_files:
        print("No .360 or .mp4 files found")
        return
    
    for vf in video_files:
        print(f"\nProcessing {vf}")
        
        creation_time = get_video_creation_time(vf)
        print(f"  Creation time: {creation_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        extractor = GoProTelemetryExtractor(str(vf))
        
        try:
            extractor.open_source()
            
            gps_data, timestamps = extractor.extract_data("GPS9")
            stream_name = "GPS9"
            
            if len(gps_data) == 0:
                print("  No GPS9, trying GPS5...")
                gps_data, timestamps = extractor.extract_data("GPS5")
                stream_name = "GPS5"
            
            if len(gps_data) > 0:
                out_gpx = vf.with_suffix(".gpx")
                write_gpx_with_extensions(gps_data, timestamps, out_gpx, vf.stem, creation_time)
                
                duration = int(np.ceil(timestamps[-1] - timestamps[0]))
                points_1hz = duration + 1
                
                print(f"    {out_gpx} ({len(gps_data)} raw points → {points_1hz} normalized @ 1Hz)")
                print(f"    First: lat={gps_data[0][0]:.6f}, lon={gps_data[0][1]:.6f}, alt={gps_data[0][2]:.1f}m, speed={gps_data[0][3]:.2f}m/s")
                print(f"    Last:  lat={gps_data[-1][0]:.6f}, lon={gps_data[-1][1]:.6f}, alt={gps_data[-1][2]:.1f}m, speed={gps_data[-1][3]:.2f}m/s")
            else:
                print(" No GPS data found (no GPS5 or GPS9 streams)")
                
        except Exception as e:
            print(f"    Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            try:
                extractor.close()
            except:
                pass


if __name__ == "__main__":
    extract_all_gps("ip")
