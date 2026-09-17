# preprocessing_functions.py
import cv2
import numpy as np
import os
from PIL import Image
from datetime import datetime

def normalize_image(img_path):
    img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        print(f"❌ Error: Could not load image: {img_path}")
        return None
    norm_img = np.zeros_like(img)
    normalized = cv2.normalize(img, norm_img, 0, 255, cv2.NORM_MINMAX)
    return normalized.astype(np.uint8)

def scale_image_with_dpi(image_array, dpi=(300, 300)):
    pil_image = Image.fromarray(image_array)
    temp_path = "_temp_scaled_image.jpg"
    pil_image.save(temp_path, dpi=dpi)
    img_bgr = cv2.imread(temp_path)
    if os.path.exists(temp_path):
        os.remove(temp_path)
    return img_bgr

def remove_noise(image, h=10, hColor=10, templateWindowSize=7, searchWindowSize=15):
    return cv2.fastNlMeansDenoisingColored(image, None, h, hColor, templateWindowSize, searchWindowSize)

def apply_thinning(image, kernel_size=5, iterations=1):
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    return cv2.erode(image, kernel, iterations=iterations)

def get_grayscale(image):
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

def process_folder_with_params(input_folder, dpi_value=300, denoise_h=10, denoise_hColor=10, 
                              templateWindowSize=7, searchWindowSize=15, kernel_size=5, iterations=1):
    valid_extensions = ('.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff')
    
    # Create output folder with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_folder = os.path.join(input_folder, f"preprocessed_images_{timestamp}")
    os.makedirs(output_folder, exist_ok=True)

    processed_count = 0
    image_files = [f for f in os.listdir(input_folder) if f.lower().endswith(valid_extensions)]
    
    if not image_files:
        return 0, output_folder
    
    for filename in image_files:
        input_path = os.path.join(input_folder, filename)

        # Step 1: Normalize
        normalized = normalize_image(input_path)
        if normalized is None:
            continue

        # Step 2: DPI Scaling
        scaled = scale_image_with_dpi(normalized, (dpi_value, dpi_value))

        # Step 3: Denoising
        denoised = remove_noise(scaled, denoise_h, denoise_hColor, templateWindowSize, searchWindowSize)

        # Step 4: Thinning
        thinned = apply_thinning(denoised, kernel_size, iterations)

        # Step 5: Grayscale Conversion
        grayscale = get_grayscale(thinned)

        # Save final output
        name, ext = os.path.splitext(filename)
        output_filename = f"{name}_preprocessed{ext}"
        output_path = os.path.join(output_folder, output_filename)

        success = cv2.imwrite(output_path, grayscale)
        if success:
            processed_count += 1
            print(f"Processed and saved: {output_path}")
        else:
            print(f"Failed to preprocess: {output_path}")
    
    return processed_count, output_folder