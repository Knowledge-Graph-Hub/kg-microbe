"""Converter utils for Bio Term Hub."""

import logging

EXCLUDE = ["biolink:Publication"]


def parse(input_filename, output_filename) -> None:
    """
    Parse KGX nodes TSV into Bio Term Hub format for OGER compatibility.

    Mapping of columns from KGX format to Bio Term Hub format,
    0.  'CUI-less' -> UMLS CUI
    1.  'N/A' -> resource from which it comes
    2.  CURIE -> native ID
    3.  name -> term (this is the field that is tokenized)
    4.  name -> preferred form
    5.  category -> type
    :param input_filename: Input file path (str)
    :param output_filename: Output file path (str)
    :return: None.
    """
    counter = 0
    outstream = open(output_filename, "w")
    header_dict = None

    with open(input_filename) as filehandler:
        for line in filehandler:
            if counter == 0:
                header = line.rstrip().split("\t")
                header_dict = parse_header(header)
                counter += 1
                continue

            elements = [x.rstrip() for x in line.split("\t")]
            if any(x in elements[header_dict["category"]] for x in EXCLUDE):
                # 'category' field is one of the ones in EXCLUDE list
                logging.info(f"Skipping line as part of excludes: {line.rstrip()}")
                continue

            if not elements[header_dict["name"]]:
                # no 'name' field for record
                print(
                    f"Skipping line as it does not have a name field: {line.rstrip()}"
                )
                continue

            parsed_record = list()
            parsed_record.append("CUI-less")
            if "provided_by" in header_dict:
                parsed_record.append(elements[header_dict["provided_by"]])
            else:
                parsed_record.append("N/A")
            parsed_record.append(elements[header_dict["id"]])
            parsed_record.append(elements[header_dict["name"]])
            parsed_record.append(elements[header_dict["name"]])
            parsed_record.append(elements[header_dict["category"]])
            if elements[header_dict["synonym"]]:
                synonyms = elements[header_dict["synonym"]]
                for s in synonyms.split("|"):
                    syn_record = [x for x in parsed_record]
                    syn_record[3] = s
                    write_line(syn_record, outstream)
            write_line(parsed_record, outstream)


def parse_header(elements) -> dict:
    """
    Parse headers from nodes TSV.

    :param elements: The header record (list)
    :return dict: A dictionary of node header names to index
    """
    header_dict = {}
    for col in elements:
        header_dict[col] = elements.index(col)
    return header_dict


def write_line(elements, outstream) -> None:
    """
    Write line to outstream.

    :param elements: The record to write (list).
    :param outstream: File handle to the output file.
    """
    outstream.write("\t".join(elements) + "\n")
