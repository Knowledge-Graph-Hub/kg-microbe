import pandas as pd

directory = "/Users/brooksantangelo/Documents/LozuponeLab/FRMS_2024/duckdb/tryptophan/"

organismal_trp = pd.read_csv(directory + "NCBI_organismal_traits.tsv",delimiter="\t")

print('length total organismal trp:', len(organismal_trp))
print('length total unique organismal trp:', len(organismal_trp.drop_duplicates(subset=["subject"])))

organismal_trp_species_only = pd.read_csv(directory + "NCBI_organismal_traits_species.tsv",delimiter="\t")

# organismal_trp_species_only = organismal_trp_species_only[organismal_trp_species_only["subject"] != organismal_trp_species_only["updated_subject"]]

duplicate_rows = organismal_trp_species_only[organismal_trp_species_only["updated_subject"].duplicated(keep=False)]
duplicate_rows = duplicate_rows.sort_values(by=["updated_subject"])

organismal_trp_species_only = organismal_trp_species_only.drop_duplicates(subset=["updated_subject"])

print('Duplicate NCBITaxon in organismal traits: ',len(duplicate_rows))
print(duplicate_rows[["subject","updated_subject"]])

print('length total organismal trp, species only:', len(organismal_trp_species_only))

genomic_trp_go = pd.read_csv(directory + "NCBI_genomic_traits_GO.tsv",delimiter="\t")

print('length total genomic trp:', len(genomic_trp_go))
print('length total unique genomic trp:', len(genomic_trp_go.drop_duplicates(subset=["new_subject"])))

overlap_trp_species = pd.read_csv(directory + "NCBI_organismal_genomic_comparison_species.tsv",delimiter="\t")

print('length total genomic, organismal overlap species level:', len(overlap_trp_species))
print('length total unique genomic, organismal overlap species level:', len(overlap_trp_species.drop_duplicates(subset=["subject_id"])))

#Figure out why these lengths differ
percentage_overlap = len(set(organismal_trp_species_only['updated_subject']).intersection(set(genomic_trp_go['new_subject']))) / len(set(organismal_trp_species_only['updated_subject'])) * 100
print("percentage organismal covered by genomic for tryptophan consumption: ",percentage_overlap)


# Try with denominator being those that are in Uniprot and in organismal traits
uniprot_proteome_organismal_overlap = pd.read_csv(directory + "Uniprot_proteome_organismal_comparison_species.tsv",delimiter="\t")

print('length total uniprot proteome, organismal overlap species level:', len(uniprot_proteome_organismal_overlap))
print('length total unique uniprot proteome, organismal overlap species level:', len(uniprot_proteome_organismal_overlap.drop_duplicates(subset=["subject_id"])))

# Get bugs that have proteome and trait, but do not have functional annotation
uniprot_proteome = pd.read_csv(directory + "Uniprot_proteome_NCBITaxa.tsv",delimiter="\t")

no_functional_annotation = set(uniprot_proteome_organismal_overlap['subject_id']) - (set(genomic_trp_go['new_subject']))
print('length total uniprot proteome and organismal overlap, no functional overlap species level:', len(no_functional_annotation))
print('unique uniprot proteome and organismal overlap, no functional overlap species level:', no_functional_annotation)

# Bugs in organismal traits/proteomes but not uniprot GO annotations
# 'NCBITaxon:431947': https://www.uniprot.org/uniprotkb/B2RH11/entry, tryptophan-tRNA ligase activity, tryprophanyl-tRNA aminoacylation
#  'NCBITaxon:837': https://www.uniprot.org/uniprotkb/A0A1R4DTR4/entry
#  'NCBITaxon:28131': https://www.uniprot.org/uniprotkb/A0A2D3L682/entry, tryptophan-tRNA ligase activity, tryprophanyl-tRNA aminoacylation
#  ***'NCBITaxon:866789': only 4 proteins, https://www.uniprot.org/uniprotkb?query=%28taxonomy_id%3A866789%29
#  ***'NCBITaxon:143388': only 20 proteins, https://www.uniprot.org/uniprotkb?dir=descend&query=%28taxonomy_id%3A143388%29&sort=gene
#  ***'NCBITaxon:1122984': no trp, https://www.uniprot.org/uniprotkb?dir=descend&query=%28taxonomy_id%3A1122984%29&sort=gene
#  ***'NCBITaxon:536056': only 12 proteins, https://www.uniprot.org/uniprotkb?dir=ascend&query=%28taxonomy_id%3A536056%29&sort=gene
#  'NCBITaxon:525325': only 1 protein, https://www.uniprot.org/uniprotkb?query=%28taxonomy_id%3A525325%29
#  'NCBITaxon:147802': https://www.uniprot.org/uniprotkb/A0A6G7BAI0/entry, tryptophan-tRNA ligase activity, tryprophanyl-tRNA aminoacylation
#  'NCBITaxon:328813': https://www.uniprot.org/uniprotkb/A0A1Y3QYY3/entry, tryptophan-tRNA ligase activity, tryprophanyl-tRNA aminoacylation, https://www.uniprot.org/uniprotkb/A0A5B3H382/entry, tryptophan synthase activity


no_proteome = set(organismal_trp_species_only['updated_subject']) - (set(uniprot_proteome['object']))
print('length unique total organismal, no proteome:', len(no_proteome))
print('unique total organismal, no proteome:', no_proteome)

# Bugs in organismal traits but not proteomes
#  NCBITaxon:631: 12k proteins, ex is https://www.uniprot.org/uniprotkb/A0A0H5M0N1/entry, tryptophan-tRNA ligase activity, tryprophanyl-tRNA aminoacylation