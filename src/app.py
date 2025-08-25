
from asyncio import sleep
import os
import multiprocessing
from pathlib import Path
from pydub import AudioSegment
from src.config import INPUT_DIR, OUTPUT_DIR
from src.metadata import add_metadata, clear_metadata, get_mutagen_obj, read_metadata
from src.utils import normalize_string
import random
import string
from rich.progress import (
            Progress,
            TextColumn,
            BarColumn,
            TaskProgressColumn,
            MofNCompleteColumn,
            TimeRemainingColumn,
        )

def prepare_paths():
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def prepare_audio(file_path, artist, album):

    clean_name = normalize_string(file_path.stem)

    output_path = OUTPUT_DIR / f'{clean_name}.mp3'
    if output_path.exists():
        rand_str = ''.join(random.choices(string.ascii_lowercase, k=3))
        output_path = OUTPUT_DIR / f'{clean_name}_{rand_str}.mp3'


    try:
        pydub_obj = AudioSegment.from_file(file_path)
        pydub_obj.set_frame_rate(44100)
        pydub_obj.export(
            out_f=output_path,
            format="mp3",
            bitrate="128k",
            codec="libmp3lame"
        )

        mutagen_obj = get_mutagen_obj(output_path)
        if not artist:
            artist = normalize_string(read_metadata('artist',mutagen_obj))
        clear_metadata(mutagen_obj)
        add_metadata('artist', artist, mutagen_obj)
        add_metadata('album', album, mutagen_obj)
    except Exception as e:
        print(f"Error when preparing audio {file_path.name} for playlist. Message: {e}")
        return f'{e}'
    
def worker(task_args):
    file, artist, album = task_args
    try:
        prepare_audio(file, artist, album)
        return f"OK: {file.name}"
    except Exception as e:
        error_message = f"ERRO: {file.name} - {e}"
        print(error_message)
        return error_message

def prepare_input_files_for_playlist(mode=0):
    tasks = []
    for sub_path in INPUT_DIR.iterdir():
        if sub_path.is_file():
            print(f"File {sub_path} not processed, files must be inside a subfolder of input.")
            continue

        artist = None
        if mode == 1:
            artist = input(f"Choose a artist name for the files in {sub_path}:\n")
        album = input(f"Choose a album name for the files in {sub_path}:\n")

        files_in_folder = [p for p in sub_path.iterdir() if p.is_file()]
        if not files_in_folder:
            print(f"No files found in {sub_path}")
            continue
        
        for file in files_in_folder:
            if file.suffix.lower() in ['.mp3', '.wav', '.m4a', '.flac']:
                tasks.append((file, artist, album))

    if not tasks:
        print("\nNenhuma tarefa para processar.")
        return

    with Progress(
    TextColumn("[progress.description]{task.description}"),
    BarColumn(),
    TaskProgressColumn(),
    MofNCompleteColumn(),
    TimeRemainingColumn(),
    ) as progress:
        main_task = progress.add_task("Processando arquivos...", total=len(tasks))
        num_processes = multiprocessing.cpu_count()
        with multiprocessing.Pool(processes=num_processes) as pool:
            for result in pool.imap_unordered(worker, tasks):
                progress.advance(main_task)
