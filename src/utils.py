import re
import string

def normalize_string(input) -> str:
    base_string = input.strip().lstrip('- / | \\ . ').replace(" ", '-')

    replacements = str.maketrans({
        ' ': '-',
        '(': '-',
        ')': '-',
        '[': '-',
        ']': '-',
        '{': '-',
        '}': '-',
        '.': ''
    })
    clean_string = base_string.translate(replacements)
    clean_string = re.sub(r'-+', '-', clean_string)
    clean_string = str(clean_string.encode('ascii', 'ignore').decode('ascii'))
    clean_string = clean_string.replace('--','-')

    return clean_string