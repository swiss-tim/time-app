import csv

def fix_csv(input_file, output_file):
    """
    Fixes a CSV file with extra commas in the data.

    Args:
        input_file (str): The path to the malformed CSV file.
        output_file (str): The path to write the fixed CSV file.
    """
    with open(input_file, 'r', encoding='utf-8') as infile, \
         open(output_file, 'w', newline='', encoding='utf-8') as outfile:
        
        writer = csv.writer(outfile)
        
        # Read header and write to output
        header = infile.readline().strip().split(',')
        num_columns = len(header)
        writer.writerow(header)

        # Process remaining lines
        for line in infile:
            fields = line.strip().split(',')
            if len(fields) > num_columns:
                # Assume extra commas are in the last column ('note')
                corrected_fields = fields[:num_columns-1]
                note = ','.join(fields[num_columns-1:])
                corrected_fields.append(note)
                writer.writerow(corrected_fields)
            else:
                writer.writerow(fields)

# Name of the uploaded file and the new fixed file
input_filename = 'time.csv'
output_filename = 'time_fixed.csv'

# Fix the CSV file
fix_csv(input_filename, output_filename)

print(f"The file '{input_filename}' has been processed and a corrected version was saved as '{output_filename}'.")