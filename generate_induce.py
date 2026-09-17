import os
import shutil
import json
import cv2
import numpy as np
from PyQt5 import QtWidgets, QtCore
from pathlib import Path

# =======================
# GUI Interface Functions
# =======================
def select_folder_dialog(parent=None, title="Select Folder"):
    """Open folder selection dialog."""
    folder = QtWidgets.QFileDialog.getExistingDirectory(
        parent=parent,
        caption=title,
        directory=""
    )
    return folder if folder else None

def show_progress_dialog(parent, title, message):
    """Show a progress dialog."""
    progress = QtWidgets.QProgressDialog(message, None, 0, 100, parent)
    progress.setWindowTitle(title)
    progress.setWindowModality(QtCore.Qt.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)
    QtWidgets.QApplication.processEvents()
    return progress

def show_message_dialog(parent, title, message, icon=QtWidgets.QMessageBox.Information):
    """Show a message dialog."""
    msg_box = QtWidgets.QMessageBox(parent)
    msg_box.setWindowTitle(title)
    msg_box.setText(message)
    msg_box.setIcon(icon)
    msg_box.exec_()

# =======================
# Core Processing Functions
# =======================
def list_images(folder):
    """List image files in folder."""
    IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")
    if not os.path.exists(folder):
        return []
    return sorted(
        [f for f in os.listdir(folder)
         if os.path.splitext(f)[1].lower() in IMAGE_EXTS]
    )

def list_jsons(folder):
    """List JSON files in folder."""
    if not os.path.exists(folder):
        return []
    return sorted(
        [f for f in os.listdir(folder)
         if f.lower().endswith(".json")]
    )

def duplicate_good_and_copy_jsons(def_dir, good_dir, progress_callback=None):
    """
    - Take ALL JSONs from def_dir (sorted).
    - Take ONE base good image from good_dir.
    - For each def JSON i:
        * create good_base_i.ext (image copy)
        * create good_base_i.json in GOOD_DIR
          with imagePath = good_base_i.ext
    """
    def_jsons = list_jsons(def_dir)
    good_images = list_images(good_dir)

    if not def_jsons:
        return False, "No JSON files found in defect folder"
    if not good_images:
        return False, "No good images found in good folder"

    # Use the FIRST good image as the base
    base_img_name = good_images[0]
    base_img_path = os.path.join(good_dir, base_img_name)
    base, ext = os.path.splitext(base_img_name)

    total = len(def_jsons)
    for idx, json_name in enumerate(def_jsons):
        i = idx + 1  # 1-based index

        def_json_path = os.path.join(def_dir, json_name)

        # New image name for this def JSON
        new_img_name = f"{base}_{i}{ext}"
        new_img_path = os.path.join(good_dir, new_img_name)

        # Copy/duplicate the base good image
        if not os.path.exists(new_img_path):
            shutil.copy2(base_img_path, new_img_path)

        # Load this specific def JSON
        with open(def_json_path, "r", encoding="utf-8") as f:
            template_data = json.load(f)

        # New JSON name based on the new image name
        new_json_name = f"{os.path.splitext(new_img_name)[0]}.json"
        new_json_path = os.path.join(good_dir, new_json_name)

        # Copy JSON content and update imagePath
        data = dict(template_data)
        data["imagePath"] = new_img_name   # only file name

        with open(new_json_path, "w", encoding="utf-8") as jf:
            json.dump(data, jf, indent=4)

        # Update progress
        if progress_callback:
            progress_callback(int((idx + 1) / total * 100))

    return True, f"Created {total} good image copies with JSONs"

def mask_from_json_folder(json_dir, output_dir_original, output_dir_masked, progress_callback=None):
    """
    For each JSON in json_dir:
      - Load image via 'imagePath' if available, else same-name .jpg
      - Build polygon mask from shapes[0].points
      - Save original grayscale + masked image to output dirs
    """
    os.makedirs(output_dir_original, exist_ok=True)
    os.makedirs(output_dir_masked, exist_ok=True)

    json_files = [f for f in os.listdir(json_dir) if f.lower().endswith(".json")]
    total = len(json_files)
    
    for idx, filename in enumerate(json_files):
        json_path = os.path.join(json_dir, filename)
        with open(json_path, "r", encoding="utf-8") as file:
            coordinates = json.load(file)

        # Get image path from JSON if possible
        image_name = None
        if isinstance(coordinates, dict) and "imagePath" in coordinates:
            image_name = coordinates["imagePath"]

        if image_name:
            image_path = os.path.join(json_dir, image_name)
        else:
            # Fallback: same name but .jpg
            image_path = json_path.replace(".json", ".jpg")

        # Load grayscale image
        image = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if image is None:
            continue

        # Create an empty mask with the same dimensions as the image
        mask = np.zeros_like(image)

        annotations = coordinates.get("shapes", [])
        if not annotations:
            continue

        points = annotations[0].get("points", [])
        if not points:
            continue

        points = np.array(points, dtype=np.int32)

        # Draw polygon on mask
        cv2.fillPoly(mask, [points], color=255)

        # Create masked image: defect area white, background black
        masked_image = np.zeros_like(image)
        masked_image[mask == 255] = 255

        base_image_name = os.path.basename(image_path)

        # Save original & masked
        original_output_path = os.path.join(output_dir_original, base_image_name)
        masked_output_path = os.path.join(output_dir_masked, base_image_name)

        cv2.imwrite(original_output_path, image)
        cv2.imwrite(masked_output_path, masked_image)

        # Update progress
        if progress_callback:
            progress_callback(int((idx + 1) / total * 100))

def generate_il_images(def_dir, good_dir, output_dir, progress_callback=None):
    """
    Use:
      def_dir/original_images + def_dir/masked_images
      good_dir/original_images + good_dir/masked_images
    to Poisson-blend every defective region onto every good image.
    """
    IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp")
    
    defective_images_dir = os.path.join(def_dir, "original_images")
    defective_masks_dir = os.path.join(def_dir, "masked_images")
    good_images_dir = os.path.join(good_dir, "original_images")
    good_masks_dir = os.path.join(good_dir, "masked_images")

    os.makedirs(output_dir, exist_ok=True)

    # Get lists of files
    def_images = [f for f in os.listdir(defective_images_dir) 
                  if os.path.splitext(f)[1].lower() in IMAGE_EXTS]
    good_images = [f for f in os.listdir(good_images_dir) 
                   if os.path.splitext(f)[1].lower() in IMAGE_EXTS]
    
    total = len(def_images) * len(good_images)
    processed = 0

    # Process each defective image and mask
    for defective_filename in def_images:
        defective_image_path = os.path.join(defective_images_dir, defective_filename)
        defect_mask_path = os.path.join(defective_masks_dir, defective_filename)

        # Verify if the defective image and mask exist
        if not os.path.exists(defect_mask_path):
            continue

        # Load the defective image and mask
        defective_image = cv2.imread(defective_image_path, cv2.IMREAD_GRAYSCALE)
        defect_mask = cv2.imread(defect_mask_path, cv2.IMREAD_GRAYSCALE)

        # Verify if images are loaded properly
        if defective_image is None or defect_mask is None:
            continue

        # Ensure the masks are binary
        _, binary_defect_mask = cv2.threshold(defect_mask, 128, 255, cv2.THRESH_BINARY)

        # Find bounding box of the defect mask
        x_def, y_def, w_def, h_def = cv2.boundingRect(binary_defect_mask)

        # Extract the relevant region from the defective image
        defective_region = defective_image[y_def:y_def + h_def, x_def:x_def + w_def]
        defect_mask_region = binary_defect_mask[y_def:y_def + h_def, x_def:x_def + w_def]

        # Check if the extracted regions are empty
        if defective_region.size == 0 or defect_mask_region.size == 0:
            continue

        # Process each good image and mask
        for good_filename in good_images:
            good_image_path = os.path.join(good_images_dir, good_filename)
            good_mask_path = os.path.join(good_masks_dir, good_filename)

            # Verify if the good image and mask exist
            if not os.path.exists(good_mask_path):
                continue

            # Load the good image and mask
            good_image = cv2.imread(good_image_path, cv2.IMREAD_GRAYSCALE)
            good_mask = cv2.imread(good_mask_path, cv2.IMREAD_GRAYSCALE)

            # Verify if images are loaded properly
            if good_image is None or good_mask is None:
                continue

            # Ensure the masks are binary
            _, binary_good_mask = cv2.threshold(good_mask, 128, 255, cv2.THRESH_BINARY)

            # Find bounding box of the good mask
            x_good, y_good, w_good, h_good = cv2.boundingRect(binary_good_mask)

            # Resize the defective region and mask to fit the good region if necessary
            if (w_def != w_good) or (h_def != h_good):
                resized_defective_region = cv2.resize(defective_region, (w_good, h_good))
                resized_defect_mask_region = cv2.resize(defect_mask_region, (w_good, h_good))
            else:
                resized_defective_region = defective_region
                resized_defect_mask_region = defect_mask_region

            # Check if the resized regions are empty
            if resized_defective_region.size == 0 or resized_defect_mask_region.size == 0:
                continue

            # Prepare inputs for seamlessClone
            good_image_color = cv2.cvtColor(good_image, cv2.COLOR_GRAY2BGR)
            src_color = cv2.cvtColor(resized_defective_region, cv2.COLOR_GRAY2BGR)

            # Ensure mask is binary uint8
            _, clone_mask = cv2.threshold(resized_defect_mask_region, 128, 255, cv2.THRESH_BINARY)
            clone_mask = clone_mask.astype(np.uint8)

            # Center where to blend on good image
            center = (x_good + w_good // 2, y_good + h_good // 2)

            # Apply Poisson blending
            manipulated_image = cv2.seamlessClone(src_color, good_image_color, clone_mask, center, cv2.NORMAL_CLONE)

            # Save the result back to good folder (IL_generated subfolder)
            output_image_path = os.path.join(
                output_dir,
                f"Generate_{os.path.splitext(good_filename)[0]}_with_{os.path.splitext(defective_filename)[0]}.png"
            )
            cv2.imwrite(output_image_path, manipulated_image)
            
            processed += 1
            if progress_callback:
                progress_callback(int((processed / total) * 100))

    return True, f"Generated {processed} synthetic defect images"

# =======================
# Main GUI Function
# =======================
def run_synthetic_defect_creation(parent=None):
    """
    Main function to run from GUI button click.
    Opens folder dialogs, processes images, and saves output in good folder.
    """
    try:
        # Step 1: Select good folder
        good_dir = select_folder_dialog(parent, "Select GOOD Image Folder")
        if not good_dir:
            return False, "Good folder selection cancelled"
        
        # Step 2: Select defect folder
        def_dir = select_folder_dialog(parent, "Select DEFECT Image Folder")
        if not def_dir:
            return False, "Defect folder selection cancelled"
        
        # Step 3: Create output directory in good folder
        output_dir = os.path.join(good_dir, "IL_generated")
        
        # Create progress dialog
        progress = show_progress_dialog(parent, "Synthetic Defect Creation", "Processing...")
        
        # Step 4: Copy and rename JSONs
        progress.setLabelText("Step 1/4: Preparing good images...")
        success, msg = duplicate_good_and_copy_jsons(def_dir, good_dir, 
                                                     lambda val: progress.setValue(val))
        if not success:
            return False, msg
        
        # Step 5: Create masks for defect folder
        progress.setLabelText("Step 2/4: Creating defect masks...")
        def_orig_out = os.path.join(def_dir, "original_images")
        def_mask_out = os.path.join(def_dir, "masked_images")
        mask_from_json_folder(def_dir, def_orig_out, def_mask_out,
                             lambda val: progress.setValue(val))
        
        # Step 6: Create masks for good folder
        progress.setLabelText("Step 3/4: Creating good masks...")
        good_orig_out = os.path.join(good_dir, "original_images")
        good_mask_out = os.path.join(good_dir, "masked_images")
        mask_from_json_folder(good_dir, good_orig_out, good_mask_out,
                             lambda val: progress.setValue(val))
        
        # Step 7: Generate synthetic defects
        progress.setLabelText("Step 4/4: Generating synthetic defects...")
        success, msg = generate_il_images(def_dir, good_dir, output_dir,
                                         lambda val: progress.setValue(val))
        
        progress.close()
        
        if success:
            # Show success message with location
            show_message_dialog(
                parent,
                "Success",
                f"Synthetic defect creation completed!\n\n"
                f"Output saved to:\n{output_dir}\n\n"
                f"Total images generated: {len(os.listdir(output_dir)) if os.path.exists(output_dir) else 0}",
                QtWidgets.QMessageBox.Information
            )
            return True, "Synthetic defects created successfully"
        else:
            return False, msg
            
    except Exception as e:
        return False, f"Error during synthetic defect creation: {str(e)}"

# =======================
# For Testing (Standalone)
# =======================
if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    
    # Test the function
    success, message = run_synthetic_defect_creation()
    
    if success:
        print("Success:", message)
    else:
        print("Error:", message)
    
    sys.exit(0 if success else 1)