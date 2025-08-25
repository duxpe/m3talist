import string

def normalize_string(input) -> str:
    base_string = input.strip()\
        .lstrip(string.digits).lstrip(' - -- | \\ / ')\
            .lstrip(string.digits).lstrip(' - -- | \\ / ')

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
    clean_string = str(clean_string.encode('ascii', 'ignore').decode('ascii'))
    clean_string = clean_string.replace('--','-')

    return clean_string