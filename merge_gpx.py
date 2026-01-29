import gpxpy
import glob
import os
from datetime import timedelta

def merge_gpx_files_sequentially(folder_path, output_file):
    
    gpx_files = sorted(glob.glob(os.path.join(folder_path, '*.gpx')))
    
    if len(gpx_files) < 2:
        print(f"Found {len(gpx_files)} GPX file(s). Need at least 2 to merge.")
        return
    
    print(f"Found {len(gpx_files)} GPX files to merge")
    
    with open(gpx_files[0], 'r') as f:
        merged_gpx = gpxpy.parse(f)
    
    last_time = None
    for track in merged_gpx.tracks:
        for segment in track.segments:
            if segment.points and segment.points[-1].time:
                last_time = segment.points[-1].time
    
    if not last_time:
        print("Error: First GPX file has no timestamps")
        return
    
    print(f"First file ends at: {last_time}")
    
    for i, gpx_file in enumerate(gpx_files[1:], start=2):
        print(f"\nProcessing file {i}/{len(gpx_files)}: {os.path.basename(gpx_file)}")
        
        with open(gpx_file, 'r') as f:
            current_gpx = gpxpy.parse(f)
        
        current_start_time = None
        for track in current_gpx.tracks:
            for segment in track.segments:
                if segment.points and segment.points[0].time:
                    current_start_time = segment.points[0].time
                    break
            if current_start_time:
                break
        
        if not current_start_time:
            print(f"  Warning: Skipping file - no timestamps found")
            continue
        
        time_offset = last_time - current_start_time
        
        print(f"  Original start: {current_start_time}")
        print(f"  Time offset: {time_offset}")
        
        for track in current_gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    if point.time:
                        point.time = point.time + time_offset
                
                if merged_gpx.tracks:
                    merged_gpx.tracks[0].segments.append(segment)
        
        for track in current_gpx.tracks:
            for segment in track.segments:
                if segment.points and segment.points[-1].time:
                    last_time = segment.points[-1].time
        
        print(f"  New end time: {last_time}")
    
    with open(output_file, 'w') as f:
        f.write(merged_gpx.to_xml())
    
    print(f"\n  Merged GPX saved to: {output_file}")
    
    total_points = sum(len(seg.points) for track in merged_gpx.tracks 
                      for seg in track.segments)
    print(f"  Total track points: {total_points}")
    print(f"  Total segments: {sum(len(track.segments) for track in merged_gpx.tracks)}")
    
    
if __name__ == "__main__":
    input_folder_path = 'ip_merge'
    output_file = 'op_merge/merged.gpx'
    merge_gpx_files_sequentially(input_folder_path, output_file)
