"""Debug parse_fasta accession extraction."""
import re

# Simulate what parse_fasta receives
header = ' [nucleotide_db] AB522418.1 Norovirus clam/Shimane/Asari1-Liquid/Jun2008/JP VP1 gene for capsid protein, partial cds'
print(f"Header: {header!r}")

# Current regex
tag_match = re.match(r'^\[([^\]]+)\]\s+', header)
print(f"tag_match: {tag_match}")
if tag_match:
    print(f"tag: {tag_match.group(0)!r}")
    remainder = header[tag_match.end():]
else:
    print("No tag match - trying space+tag")
    # Strip leading spaces first
    stripped = header.lstrip()
    print(f"Stripped: {stripped!r}")
    tag_match = re.match(r'^\[([^\]]+)\]\s+', stripped)
    if tag_match:
        print(f"tag: {tag_match.group(0)!r}")
        remainder = stripped[tag_match.end():]
        print(f"remainder: {remainder!r}")
    else:
        # Split on space and take first word
        parts = header.split(None, 1)
        print(f"parts: {parts}")
        raw_acc = parts[0]
        print(f"raw_acc: {raw_acc!r}")
        remainder = parts[1] if len(parts) > 1 else ""

parts = remainder.split(None, 1)
print(f"final parts: {parts}")
raw_acc = parts[0]
print(f"accession: {raw_acc!r}")
