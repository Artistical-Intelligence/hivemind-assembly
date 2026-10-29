"""Local OCR of a bounded debugging screenshot; no files or network uploads."""
import asyncio
import csv
import io
import os
import subprocess
import sys

from hivemind_assembly.learning.documents import tesseract

OCR_SECONDS = 15
MAX_WORDS = 1200


def available():
    return bool(tesseract())


def words_from_tsv(raw):
    words = []
    truncated = False
    for row in csv.DictReader(io.StringIO(raw), delimiter='\t', quoting=csv.QUOTE_NONE):
        text = (row.get('text') or '').strip()
        if row.get('level') != '5' or not text:
            continue
        try:
            box = {k: int(row[k]) for k in ('left', 'top', 'width', 'height')}
            confidence = float(row['conf'])
        except (KeyError, TypeError, ValueError):
            continue
        if any(value < 0 or value > 2560 for value in box.values()) or not 0 <= confidence <= 100:
            continue
        if len(words) == MAX_WORDS:
            truncated = True
            break
        words.append({'text': text[:200], 'confidence': confidence, 'box': box})
    return {'text': ' '.join(w['text'] for w in words), 'words': words, 'truncated': truncated}


async def recognize(picture):
    program = tesseract()
    if not program:
        return {'state': 'unavailable', 'message': 'Select Install required tools in HA Settings to add Tesseract. The screenshot is still available for visual review.'}
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if sys.platform == 'win32' else 0
    process = await asyncio.create_subprocess_exec(
        program, 'stdin', 'stdout', '-l', 'eng', '--psm', '11', 'tsv',
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=dict(os.environ, OMP_THREAD_LIMIT='1'), creationflags=flags,
    )
    try:
        stdout, _stderr = await asyncio.wait_for(process.communicate(picture), OCR_SECONDS)
        if process.returncode:
            return {'state': 'error', 'message': 'Local OCR failed. Review the screenshot directly.'}
        if len(stdout) > 2_000_000:
            return {'state': 'error', 'message': 'OCR output exceeded its limit. Review the screenshot directly.'}
        return {'state': 'ready', 'engine': 'Tesseract', 'language': 'eng',
                'coordinates': 'Screenshot pixels; OCR text may be inaccurate.',
                **words_from_tsv(stdout.decode('utf-8', 'replace'))}
    except TimeoutError:
        return {'state': 'timeout', 'message': 'Local OCR reached its time limit. The screenshot is still available.'}
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()
