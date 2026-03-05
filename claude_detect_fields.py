"""
claude_detect_fields.py

Uses Claude AI to automatically detect ALL form fields from a scanned PDF
and generate a fields.json file — with empty values ready for you to fill in later.

Usage:
    python3 claude_detect_fields.py <input.pdf> <output_fields.json>

Example:
    python3 claude_detect_fields.py form.pdf fields.json
"""

import anthropic
import base64
import json
import sys
import os
import subprocess
from pathlib import Path


# ---------------------------------------------------------------
# Step 1: Convert PDF to images
# ---------------------------------------------------------------
def convert_pdf_to_images(pdf_path: str, images_dir: str):
    print(f"Converting PDF to images...")
    os.makedirs(images_dir, exist_ok=True)

    skill_script = Path(__file__).parent / "scripts" / "convert_pdf_to_images.py"
    if not skill_script.exists():
        raise FileNotFoundError(
            f"Could not find convert_pdf_to_images.py at {skill_script}\n"
            "Make sure you run this script from your ~/skills/skills/pdf/ directory."
        )

    result = subprocess.run(
        ["python3", str(skill_script), pdf_path, images_dir],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"PDF conversion failed:\n{result.stderr}")

    images = sorted(Path(images_dir).glob("*.png"))
    if not images:
        raise FileNotFoundError(f"No images found in {images_dir} after conversion.")
    print(f"Converted {len(images)} page(s) to images.")
    return [str(p) for p in images]


# ---------------------------------------------------------------
# Step 2: Send each page image to Claude — detect fields only
# ---------------------------------------------------------------
def detect_fields_with_claude(image_paths: list) -> dict:
    print(f"Asking Claude to detect all form fields...")

    client = anthropic.Anthropic()
    all_fields = []
    page_dimensions = []

    for page_num, image_path in enumerate(image_paths, start=1):
        print(f"   Analyzing page {page_num}...")

        with open(image_path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")

        try:
            from PIL import Image
            with Image.open(image_path) as img:
                img_width, img_height = img.size
        except ImportError:
            img_width, img_height = 1700, 2200

        page_dimensions.append({
            "page_number": page_num,
            "image_width": img_width,
            "image_height": img_height
        })

        prompt = f"""You are analyzing page {page_num} of a scanned PDF form.
The image dimensions are {img_width}x{img_height} pixels.

Detect ALL form fields on this page: text fields, checkboxes, radio buttons, dropdowns, signature fields, date fields — everything.

For each field return:
- The label text as shown on the form
- A brief description of what the field is for
- Pixel coordinates of the label bounding box
- Pixel coordinates of the entry area (where someone would write or tick)
- Leave "text" as empty string — we are not filling values yet

Return ONLY a JSON array (no explanation, no markdown) in this exact format:
[
  {{
    "page_number": {page_num},
    "description": "Brief description of what this field is for",
    "field_label": "Label text as shown on form",
    "label_bounding_box": [x0, y0, x1, y1],
    "entry_bounding_box": [x0, y0, x1, y1],
    "entry_text": {{
      "text": "",
      "font_size": 10
    }}
  }}
]

Rules:
- Coordinates must be pixels in a {img_width}x{img_height} image
- x0,y0 = top-left corner, x1,y1 = bottom-right corner
- Detect every single field, even optional ones
- For checkboxes, make the entry_bounding_box fit tightly around the checkbox square"""

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_data
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        try:
            page_fields = json.loads(raw)
            all_fields.extend(page_fields)
            print(f"   Found {len(page_fields)} field(s) on page {page_num}")
        except json.JSONDecodeError as e:
            print(f"   Could not parse Claude's response for page {page_num}: {e}")

    return {
        "pages": page_dimensions,
        "form_fields": all_fields
    }


# ---------------------------------------------------------------
# Step 3: Save fields.json
# ---------------------------------------------------------------
def save_fields_json(fields_data: dict, output_path: str):
    with open(output_path, "w") as f:
        json.dump(fields_data, f, indent=2)
    print(f"Saved to: {output_path}")


# ---------------------------------------------------------------
# Main
# ---------------------------------------------------------------
def main():
    if len(sys.argv) != 3:
        print("Usage: python3 claude_detect_fields.py <input.pdf> <output_fields.json>")
        print("\nExample:")
        print("  python3 claude_detect_fields.py form.pdf fields.json")
        sys.exit(1)

    pdf_path    = sys.argv[1]
    output_path = sys.argv[2]

    if not Path(pdf_path).exists():
        print(f"PDF not found: {pdf_path}")
        sys.exit(1)

    images_dir  = "claude_form_images"
    image_paths = convert_pdf_to_images(pdf_path, images_dir)
    fields_data = detect_fields_with_claude(image_paths)
    save_fields_json(fields_data, output_path)

    total = len(fields_data["form_fields"])
    print(f"\nDone! Detected {total} field(s) across {len(image_paths)} page(s).")
    print(f"\nNext steps:")
    print(f"  1. Open {output_path} and fill in the 'text' values for each field")
    print(f"  2. Validate:  python3 scripts/check_bounding_boxes.py {output_path}")
    print(f"  3. Fill form: python3 scripts/fill_pdf_form_with_annotations.py {pdf_path} {output_path} filled_output.pdf")


if __name__ == "__main__":
    main()
