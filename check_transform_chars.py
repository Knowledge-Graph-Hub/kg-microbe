#!/usr/bin/env python3
import csv
import sys
import argparse

def contains_offending_whitespace(text):
    """Return True if text contains a tab, newline, or carriage return."""
    for char in text:
        if char in ("\t", "\n", "\r"):
            return True
    return False

def decode_lines(file_obj):
    """
    Generator that decodes each binary line as UTF-8.
    If a non-UTF-8 sequence is found (resulting in a Unicode replacement character),
    a warning message is printed.
    """
    for line_number, byte_line in enumerate(file_obj, start=1):
        decoded_line = byte_line.decode('utf-8', errors='replace')
        if "\ufffd" in decoded_line:
            warning_message = (
                f"Warning: Non-UTF-8 character detected in line {line_number}: "
                f"{decoded_line.strip()}"
            )
            sys.stderr.write(warning_message + "\n")
            print(warning_message)
        yield decoded_line

def process_tsv(input_path, output_path=None):
    # Open the input file in binary mode so we can decode manually.
    with open(input_path, 'rb') as infile:
        # Use the custom generator to decode each line and check for non-UTF-8 bytes.
        decoded_lines = decode_lines(infile)
        
        # Use csv.reader to parse the TSV data.
        reader = csv.reader(decoded_lines, delimiter='\t')
        
        # If an output path is given, open it in binary write mode.
        if output_path:
            outfile = open(output_path, 'wb')
        else:
            # Write to standard output (using its buffer to write bytes).
            outfile = sys.stdout.buffer

        # Process each row.
        for row_index, row in enumerate(reader, start=1):
            # Check each field for offending whitespace.
            for col_index, field in enumerate(row, start=1):
                # Collect all offending characters found in the field.
                offenders = [repr(c) for c in field if c in ("\t", "\n", "\r")]
                if offenders:
                    warning_message = (
                        f"Warning: Row {row_index}, Column {col_index} contains offending character(s): "
                        f"{', '.join(offenders)}"
                    )
                    sys.stderr.write(warning_message + "\n")
                    print(warning_message)
            # Reassemble the row into a TSV-formatted string.
            output_line = "\t".join(row) + "\n"
            # Encode back to UTF-8 and write out.
            outfile.write(output_line.encode('utf-8'))
        
        if output_path:
            outfile.close()

def main():
    parser = argparse.ArgumentParser(
        description="Decode and re-encode a TSV file in UTF-8, checking for non-UTF-8 characters and "
                    "offending tab/newline/carriage-return characters."
    )
    parser.add_argument("input_file", help="Path to the input TSV file.")
    parser.add_argument(
        "-o", "--output", help="Path to the output file. If omitted, output is sent to stdout."
    )
    args = parser.parse_args()
    process_tsv(args.input_file, args.output)

if __name__ == "__main__":
    main()

