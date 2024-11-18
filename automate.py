import os
import glob
import base64
from typing import List, Set
import logging
from dataclasses import dataclass
import pandas as pd
from fuzzywuzzy import fuzz
from openai import OpenAI


def load_env():
    env_file = ".env"
    with open(env_file, "r") as file:
        for line in file:
            if line.strip() and not line.startswith("#"):
                key, value = line.strip().split("=", 1)
                os.environ[key] = value


load_env()

SHEETS_DIR = "sheets"
IMAGES_DIR = "images"
OUTPUT_DIR = "output_sheets"
LOG_FILE = "attendance_processing.log"


organization = os.getenv("ORG")
project = os.getenv("PROJECT")
api_key = os.getenv("API_KEY")


print("organization", organization)
print("project", project)
print("apijey", api_key)


logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


@dataclass
class StudentRecord:
    first_name: str
    last_name: str
    full_name: str
    file_name: str
    row_index: int


def encode_image(image_path: str) -> str:
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


class AttendanceProcessor:
    def __init__(self):
        self.client = OpenAI(
            api_key=api_key,
            organization=organization,
            project=project,
        )
        self.students: List[StudentRecord] = []
        self.processed_names: Set[str] = set()
        self.sheet_names: List[str] = []
        self.all_possible_names: Set[str] = set()

        os.makedirs(OUTPUT_DIR, exist_ok=True)

    def load_sheets(self):
        sheet_files = glob.glob(f"{SHEETS_DIR}/*.csv")
        self.sheet_names = [os.path.basename(f) for f in sheet_files]

        print("\nAvailable sheets for matching:")
        for sheet in self.sheet_names:
            print(f"- {sheet}")
        print()

        for sheet_file in sheet_files:
            try:
                df = pd.read_csv(sheet_file)
                required_columns = ["First Name", "Last Name", "Points"]
                if not all(col in df.columns for col in required_columns):
                    logging.error(
                        f"Missing required columns in {sheet_file}. Required: {required_columns}"
                    )
                    continue

                for row_idx, row in df.iterrows():
                    first_name = str(row["First Name"]).strip()
                    last_name = str(row["Last Name"]).strip()
                    full_name = f"{first_name} {last_name}"

                    self.all_possible_names.add(full_name.lower())

                    student = StudentRecord(
                        first_name=first_name,
                        last_name=last_name,
                        full_name=full_name,
                        file_name=os.path.basename(sheet_file),
                        row_index=row_idx,
                    )
                    self.students.append(student)

                output_path = os.path.join(OUTPUT_DIR, os.path.basename(sheet_file))
                df.to_csv(output_path, index=False)

            except Exception as e:
                logging.error(f"Error processing sheet {sheet_file}: {str(e)}")

        all_names_formatted = "\n".join(
            sorted(name.title() for name in self.all_possible_names)
        )
        print("Valid student names for matching:")
        print(all_names_formatted)
        print()

    def process_image(
        self, image_path: str, attempt: int = 1, max_attempts: int = 3
    ) -> List[str]:
        try:
            base64_image = encode_image(image_path)

            valid_names = "\n".join(
                sorted(name.title() for name in self.all_possible_names)
            )

            base_prompt = f"""This is a student assignment. The student names are written at the top in the 'names:' or 'Names:' line.
            There will be between 1-5 names on this line. These names MUST be from the following list of valid students:

            {valid_names}

            Return ONLY names that exactly match students from this list, separated by newlines.
            The names MUST be from the list above - do not return any names that don't match exactly.
            Look carefully at the top of the assignment for the names line. There's even a chance it's in cursive
            
            You must not miss ANY names. There's a chance the student overflowed the name from the name line and put it under,
            you should detect that. We need this for attendence
            """

            if attempt > 1:
                base_prompt += f"""

                This is attempt {attempt} because some names weren't found in the previous attempts.
                Please look VERY carefully at the names line.
                These are handwritten assignments, so the names might be slightly messy but they ARE there.
                Double check for last name, first name format and different handwriting styles.
                The names MUST be from the provided list - they are definitely there, just need to be found."""

            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": base_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                },
                            },
                        ],
                    }
                ],
                max_tokens=300,
            )

            names = response.choices[0].message.content.strip().split("\n")
            detected_names = [name.strip() for name in names if name.strip()]

            valid_detected_names = [
                name
                for name in detected_names
                if name.lower() in self.all_possible_names
            ]

            if len(valid_detected_names) == 0 and attempt < max_attempts:
                print(f"No valid names found on attempt {attempt}, retrying...")
                return self.process_image(image_path, attempt + 1, max_attempts)

            if attempt > 1:
                print(f"Found names on attempt {attempt}")

            return valid_detected_names

        except Exception as e:
            logging.error(f"Error processing image {image_path}: {str(e)}")
            print(f"Error code: {type(e).__name__} - {str(e)}")
            return []

    def match_name(self, detected_name: str) -> StudentRecord:

        for student in self.students:
            if student.full_name.lower() == detected_name.lower():
                return student

        best_match = None
        best_ratio = 0

        for student in self.students:
            ratio = fuzz.token_sort_ratio(
                detected_name.lower(), student.full_name.lower()
            )
            if ratio > best_ratio and ratio >= 95:
                best_ratio = ratio
                best_match = student

        if not best_match:
            print(f"\nWarning: No exact match found for '{detected_name}'")
            print("This shouldn't happen as we're only accepting valid names.")
            print("Please check the vision API output.")

        return best_match

    def mark_attendance(self, student: StudentRecord):
        try:
            output_file = os.path.join(OUTPUT_DIR, student.file_name)
            df = pd.read_csv(output_file)
            df.at[student.row_index, "Points"] = 10
            df.to_csv(output_file, index=False)
            logging.info(f"Marked attendance for {student.full_name}")
        except Exception as e:
            logging.error(f"Error marking attendance for {student.full_name}: {str(e)}")

    def process_all_images(self):
        image_files = []
        for ext in ["jpg", "jpeg", "png"]:
            image_files.extend(glob.glob(f"{IMAGES_DIR}/*.{ext}"))

        total_images = len(image_files)
        for idx, image_file in enumerate(image_files, 1):
            print(
                f"\nProcessing image {idx}/{total_images}: {os.path.basename(image_file)}"
            )
            detected_names = self.process_image(image_file)

            print(f"Found {len(detected_names)} names in image: {detected_names}")
            for detected_name in detected_names:
                if detected_name in self.processed_names:
                    print(f"Already processed {detected_name}")
                    continue

                student = self.match_name(detected_name)
                if student:
                    print(
                        f"Matched {detected_name} to {student.full_name} in {student.file_name}"
                    )
                    self.mark_attendance(student)
                    self.processed_names.add(detected_name)
                else:
                    print(
                        f"ERROR: Could not find matching student for name: {detected_name}"
                    )
                    print("This should never happen as we only accept valid names.")
                    logging.error(
                        f"Could not find matching student for name: {detected_name}"
                    )


def main():
    processor = AttendanceProcessor()
    print("Loading sheets...")
    processor.load_sheets()
    print(f"Loaded {len(processor.students)} students from sheets")
    print("\nProcessing images...")
    processor.process_all_images()
    print("\nAttendance processing completed")
    print(f"Results have been saved to {OUTPUT_DIR}/")
    logging.info("Attendance processing completed")


if __name__ == "__main__":
    main()
