#!/usr/bin/env python3
"""
Simplified Panorama Rectification Tool - Version 2 (More Viewpoints)
Based on the A-Contrario Horizon-First Vanishing Point Detection algorithm

Improvements:
- Increased render viewpoints from 4 to 8 for better vanishing point detection
- More accurate consensus calculation with additional viewpoints

Usage: python simple_rectify_v2.py input_folder output_folder
"""

import os
import sys
import glob
import numpy as np
import skimage.io
from PIL import Image
from scipy.ndimage import map_coordinates

# Add current directory to Python path for local imports
current_dir = os.path.dirname(os.path.abspath(__file__))
panorama_dir = os.path.join(current_dir, 'Panorama_Rectification')
sys.path.insert(0, current_dir)
sys.path.insert(0, panorama_dir)

# Import rectification modules
from Panorama_Rectification.default_params import default_params
from Panorama_Rectification.Panos.Pano_rectification import simon_rectification
from Panorama_Rectification.Panos.Pano_project import render_imgs
from Panorama_Rectification.Panos.Pano_visualization import R_heading, R_roll, R_pitch
from Panorama_Rectification.Panos.Pano_zp_hvp import calculate_consensus_zp
from Panorama_Rectification.Panos.Pano_histogram import calculate_histogram
from Panorama_Rectification.Panos.Pano_new_pano import calculate_new_pano


def rectify_single_panorama(input_path, output_path, temp_dir=None):
    """
    Rectify a single panoramic image using the Simon algorithm
    
    Args:
        input_path (str): Path to input panoramic image
        output_path (str): Path to save rectified image
        temp_dir (str): Temporary directory for intermediate files
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Load image
        im = Image.open(input_path)
        panorama_img = skimage.io.imread(input_path)
        
        # Create temporary directory if not provided
        if temp_dir is None:
            temp_dir = os.path.join(os.path.dirname(output_path), 'temp')
        
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
        
        # Clean temporary directory
        temp_files = glob.glob(os.path.join(temp_dir, '*.jpg'))
        for temp_file in temp_files:
            os.remove(temp_file)
        
        print(f"Processing: {os.path.basename(input_path)}")
        
        # Step 1: Render multiple viewpoints (8 views at 45° intervals for better accuracy)
        render_num = 8
        tilelist = render_imgs(panorama_img, temp_dir, save_directly=True)
        
        # Step 2: Detect vanishing points for each viewpoint
        hl = []
        hvps = []
        hvp_groups = []
        z = []
        z_group = []
        ls = []
        z_homo = []
        hvp_homo = []
        ls_homo = []
        
        for i in range(len(tilelist)):
            result = simon_rectification(tilelist[i], i, temp_dir, '', '1')
            [tmp_hl, tmp_hvps, tmp_hvp_groups, tmp_z, tmp_z_group, tmp_ls, 
             tmp_z_homo, tmp_hvp_homo, tmp_ls_homo, params] = result
            
            hl.append(tmp_hl)
            hvps.append(tmp_hvps)
            hvp_groups.append(tmp_hvp_groups)
            z.append(tmp_z)
            z_group.append(tmp_z_group)
            ls.append(tmp_ls)
            z_homo.append(tmp_z_homo)
            hvp_homo.append(tmp_hvp_homo)
            ls_homo.append(tmp_ls_homo)
        
        # Clean temporary files
        temp_files = glob.glob(os.path.join(temp_dir, '*.jpg'))
        for temp_file in temp_files:
            os.remove(temp_file)
        
        # Step 3: Calculate consensus zenith point from all viewpoints
        zenith_points = np.array([R_heading(np.pi / 4 * (i - 1)).dot(zenith) 
                                 for i, zenith in enumerate(z_homo)])
        
        [zenith_consensus, best_zenith] = calculate_consensus_zp(zenith_points, method='svd')
        
        # Step 4: Calculate pitch and roll angles
        pitch = np.arctan(best_zenith[2] / best_zenith[1])
        roll = -np.arctan(best_zenith[0] / (np.sign(best_zenith[1]) * 
                                           np.hypot(best_zenith[1], best_zenith[2])))
        
        print(f"  Detected pitch: {np.degrees(pitch):.2f}°")
        print(f"  Detected roll: {np.degrees(roll):.2f}°")
        
        # Step 5: Create rectified panorama
        height = im.height
        width = im.width
        
        # Generate coordinate grid for the entire panorama
        u, v = np.mgrid[-np.pi/2:np.pi/2:height*1j, -np.pi:np.pi:width*1j]
        
        # Convert spherical coordinates to 3D coordinates
        y = np.sin(u)
        x = np.cos(u) * np.sin(v)
        z = np.cos(u) * np.cos(v)
        
        # Apply rectification transformations
        coordinates = np.array([x, y, z]).transpose([1, 2, 0]).reshape(-1, 3)
        coordinates = R_pitch(pitch).dot(R_roll(roll).dot(coordinates.T)).T
        
        # Convert back to panorama coordinates
        coordinates = calculate_new_pano(coordinates, im)
        coordinates = coordinates.reshape(2, height, width)
        
        # Apply coordinate mapping to rectify the image
        img = skimage.io.imread(input_path)
        rectified_img = np.dstack([
            map_coordinates(img[:, :, 0], coordinates, order=1),
            map_coordinates(img[:, :, 1], coordinates, order=1),
            map_coordinates(img[:, :, 2], coordinates, order=1)
        ])
        
        # Save rectified image
        skimage.io.imsave(output_path, rectified_img.astype(np.uint8))
        print(f"  Saved rectified image: {output_path}")
        
        return True
        
    except Exception as e:
        print(f"Error processing {input_path}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def rectify_folder(input_folder, output_folder):
    """
    Rectify all panoramic images in a folder
    
    Args:
        input_folder (str): Path to folder containing input images
        output_folder (str): Path to folder for output images
    """
    # Create output directory if it doesn't exist
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    
    # Create temporary directory
    temp_dir = os.path.join(output_folder, 'temp')
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)
    
    # Find all image files
    image_extensions = ['*.jpg', '*.jpeg', '*.png', '*.JPG', '*.JPEG', '*.PNG']
    image_files = []
    
    for ext in image_extensions:
        image_files.extend(glob.glob(os.path.join(input_folder, ext)))
    
    image_files.sort()
    
    if not image_files:
        print(f"No image files found in {input_folder}")
        return
    
    print(f"Found {len(image_files)} images to process")
    
    success_count = 0
    
    for img_path in image_files:
        # Generate output filename
        base_name = os.path.splitext(os.path.basename(img_path))[0]
        output_path = os.path.join(output_folder, f"rectified_{base_name}.jpg")
        
        # Skip if output already exists
        if os.path.exists(output_path):
            print(f"Skipping {base_name} (already exists)")
            continue
        
        # Rectify the image
        if rectify_single_panorama(img_path, output_path, temp_dir):
            success_count += 1
    
    # Clean up temporary directory
    try:
        temp_files = glob.glob(os.path.join(temp_dir, '*'))
        for temp_file in temp_files:
            os.remove(temp_file)
        os.rmdir(temp_dir)
    except:
        pass
    
    print(f"\nCompleted: {success_count}/{len(image_files)} images successfully rectified")


def main():
    """Main function to handle command line arguments"""
    if len(sys.argv) != 3:
        print("Usage: python simple_rectify_v2.py input_folder output_folder")
        print("")
        print("This tool rectifies panoramic images using enhanced parameters:")
        print("- 8 viewpoints for better vanishing point detection")
        print("- Improved consensus calculation")
        print("")
        print("Supported formats: JPG, JPEG, PNG")
        sys.exit(1)
    
    input_folder = sys.argv[1]
    output_folder = sys.argv[2]
    
    # Validate input folder
    if not os.path.exists(input_folder):
        print(f"Error: Input folder '{input_folder}' does not exist")
        sys.exit(1)
    
    if not os.path.isdir(input_folder):
        print(f"Error: '{input_folder}' is not a directory")
        sys.exit(1)
    
    print("Panorama Rectification Tool v2 (8 Viewpoints)")
    print("=" * 50)
    print(f"Input folder:  {input_folder}")
    print(f"Output folder: {output_folder}")
    print("")
    
    # Start processing
    rectify_folder(input_folder, output_folder)


if __name__ == "__main__":
    main()