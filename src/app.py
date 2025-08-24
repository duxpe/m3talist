
from pathlib import Path
from pydub import AudioSegment
from src.config import INPUT_DIR, OUTPUT_DIR
from src.metadata import add_metadata, clear_metadata, get_mutagen_obj

def prepare_audio(file_path, artist, album):
    name = file_path.name.strip()

    replacements = str.maketrans({
        '(': '-',
        ')': '-',
        '[': '-',
        ']': '-',
    })
    sanitized = name.translate(replacements)
    clean_name = sanitized.encode('ascii', 'ignore').decode('ascii')

    output_path = OUTPUT_DIR / clean_name

    try:
        pydub_obj = AudioSegment.from_mp3(file_path)
        pydub_obj.set_frame_rate(44100)
        pydub_obj.export(
            out_f=output_path,
            format="mp3",
            bitrate="128k",
            codec="libmp3lame"
        )

        mutagen_obj = get_mutagen_obj(output_path)
        clear_metadata(mutagen_obj)
        add_metadata('artist', artist, mutagen_obj)
        add_metadata('album', album, mutagen_obj)
    except Exception as e:
        print(f"Error when preparing audio {file_path.name} for playlist. Message: {e}")


def prepare_input_files_for_playlist():
    for sub_path in INPUT_DIR.iterdir():
        if sub_path.is_file():
            print(f"File {sub_path} not processed, files must be inside a subfolder of input.")
            continue

        artist = input(f"Choose a artist name for the files in {sub_path}:\n")
        album = input(f"Choose a album name for the files in {sub_path}:\n")

        for file in sub_path.iterdir():
            prepare_audio(file, artist, album)
