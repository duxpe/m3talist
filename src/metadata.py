import mutagen
from mutagen.id3 import ID3, TPE1
from mutagen.id3 import TDOR

from src.config import INPUT_DIR

def get_mutagen_obj(file_path):
    return mutagen.File(file_path)


def clear_metadata(file):
    file.delete()

def print_all_metadata(file):
    print(file.pprint())

def translate_metadata_key_to_id3(metadata_name):
    clean_name = (metadata_name or '').strip().lower()
    frame_id = clean_name

    if clean_name in ('artist', 'artista', 'singer', 'author', 'tpe1'):
        frame_id = 'TPE1'
    elif clean_name in ('album artist', 'artista do álbum', 'artista do album', 'albumartist', 'band', 'tpe2'):
        frame_id = 'TPE2'
    elif clean_name in ('title', 'título', 'titulo', 'track title', 'trackname', 'tit2', 'name'):
        frame_id = 'TIT2'
    elif clean_name in ('album', 'álbum', 'album name', 'talb'):
        frame_id = 'TALB'
    elif clean_name in ('track', 'tracknumber', 'número da faixa', 'numero da faixa', 'faixa', 'trck'):
        frame_id = 'TRCK'
    elif clean_name in ('disc', 'disco', 'número de partes', 'numero de partes', 'partes', 'tpos', 'discnumber'):
        frame_id = 'TPOS'
    elif clean_name in ('genre', 'gênero', 'genero', 'tcon'):
        frame_id = 'TCON'
    elif clean_name in ('year', 'ano', 'data', 'date', 'tdrc', 'tyer'):
        frame_id = 'TDRC'
    elif clean_name in ('composer', 'compositor', 'tcom'):
        frame_id = 'TCOM'
    elif clean_name in ('comment', 'comentário', 'comentario', 'comm'):
        frame_id = 'COMM'
    elif clean_name in ('subtitle', 'legenda', 'subtítulo', 'subtitulo', 'tit3'):
        frame_id = 'TIT3'
    elif clean_name in ('conductor', 'regente', 'tpe3'):
        frame_id = 'TPE3'
    elif clean_name in ('arranger', 'arranjador', 'arranjo', 'tpe4', 'remixer'):
        frame_id = 'TPE4'
    elif clean_name in ('original artist', 'artista original', 'tope'):
        frame_id = 'TOPE'
    elif clean_name in ('original year', 'ano original', 'tory', 'tdor'):
        frame_id = 'TDOR'
    elif clean_name in ('lyrics', 'letra', 'letra não sincronizada', 'letra nao sincronizada', 'uslt'):
        frame_id = 'USLT'

    return frame_id


def read_metadata(metadata_name, file):
    id3_name = translate_metadata_key_to_id3(metadata_name)
    data = str(file.get(id3_name))
    return data


def add_metadata(metadata_name, metadata_content, file):
    from mutagen.id3 import (
        TPE1, TPE2, TIT2, TALB, TRCK, TPOS, TCON, TDRC, TCOM, COMM,
        TIT3, TPE3, TPE4, TOPE, TORY, USLT, TDOR
    )

    frame = None
    frame_id = translate_metadata_key_to_id3(metadata_name)

    if frame_id == 'TPE1':
        frame = TPE1(encoding=3, text=[str(metadata_content)])
    elif frame_id == 'TPE2':
        frame = TPE2(encoding=3, text=[str(metadata_content)])
    elif frame_id == 'TIT2':
        frame = TIT2(encoding=3, text=[str(metadata_content)])
    elif frame_id == 'TALB':
        frame = TALB(encoding=3, text=[str(metadata_content)])
    elif frame_id == 'TRCK':
        frame = TRCK(encoding=3, text=[str(metadata_content)])
    elif frame_id == 'TPOS':
        frame = TPOS(encoding=3, text=[str(metadata_content)])
    elif frame_id == 'TCON':
        frame = TCON(encoding=3, text=[str(metadata_content)])
    elif frame_id == 'TDRC':
        frame = TDRC(encoding=3, text=[str(metadata_content)])
    elif frame_id == 'TCOM':
        frame = TCOM(encoding=3, text=[str(metadata_content)])
    elif frame_id == 'COMM':
        frame = COMM(encoding=3, lang='eng', desc='', text=[str(metadata_content)])
    elif frame_id == 'TIT3':
        frame = TIT3(encoding=3, text=[str(metadata_content)])
    elif frame_id == 'TPE3':
        frame = TPE3(encoding=3, text=[str(metadata_content)])
    elif frame_id == 'TPE4':
        frame = TPE4(encoding=3, text=[str(metadata_content)])
    elif frame_id == 'TOPE':
        frame = TOPE(encoding=3, text=[str(metadata_content)])
    elif frame_id == 'TDOR':
        try:
            frame = TDOR(encoding=3, text=[str(metadata_content)])
        except Exception:
            frame_id = 'TORY'
            frame = TORY(encoding=3, text=[str(metadata_content)])
    elif frame_id == 'USLT':
        frame = USLT(encoding=3, lang='eng', desc='', text=str(metadata_content))
    else:
        raise ValueError(f"Unsupported metadata field: {metadata_name}")

    if file.tags is None:
        file.add_tags()
    try:
        file.tags.setall(frame_id, [frame])
    except Exception:
        file.tags.add(frame)
    file.save()


def define_normalized_metadata_for_folder(folder_name, album_name, artist=None):
    DIR = INPUT_DIR / folder_name
    for file in DIR.iterdir():
        audio_file = get_mutagen_obj(file)

        clear_metadata(audio_file)
        add_metadata('artist',artist, audio_file)
        add_metadata('album', album_name, audio_file)