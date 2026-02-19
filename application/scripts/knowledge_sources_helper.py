#This script processes the knowledge_sources dictionary to ensure that all filenames have the .pdf extension.

import re

# Path to the python file
file_path = 'knowledge_sources.py'

# Read the content of the python file
with open(file_path, 'r') as file:
    content = file.read()

# Regex pattern to match dictionary keys (filenames)
pattern = r'\"([^\"]+)\"\s*:\s*\{'

# Function to ensure .pdf extension in filenames
def ensure_pdf_extension(match):
    filename = match.group(1)
    if not filename.lower().endswith('.pdf'):
        filename += '.pdf'
    return f'"{filename}": {{'

# Update all filenames in the knowledge_sources dictionary
updated_content = re.sub(pattern, ensure_pdf_extension, content)

# Write the updated content back to the file
with open(file_path, 'w') as file:
    file.write(updated_content)

print("The knowledge_sources.py file has been updated successfully.")
