"""Decoding and encoding strings such that everything is utf8."""

import re

import chardet


def process_and_decode_label(label):
    """
    Process and decode a label string.

    :param label: A string to process and decode.
    :return: A processed and decoded string.
    """
    # Remove HTML tags and extra spaces
    label = re.sub(r"</?[lLiI]>|\s+|<[^>]+>", " ", label).strip()

    # Detect encoding
    detected_encoding = chardet.detect(label.encode())
    encoding = detected_encoding["encoding"]
    confidence = detected_encoding["confidence"]

    try:
        # Attempt to decode with the detected encoding if it's not UTF-8 or confidence is low
        if encoding.lower() != "utf-8" or confidence < 0.9:
            label = label.encode("utf-8").decode(encoding, errors="ignore")
    except (UnicodeDecodeError, UnicodeEncodeError):
        # Fallback: ignore errors during decoding
        label = label.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")

    return label


def clean_string(input_str):
    """Clean string from punctuations and whitespaces."""
    if not isinstance(input_str, str):
        return input_str
    # Remove newline characters
    cleaned_str = input_str.replace("\n", " ")

    # Remove extra spaces
    cleaned_str = " ".join(cleaned_str.split())

    return cleaned_str
