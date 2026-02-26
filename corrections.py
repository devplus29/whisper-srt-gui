# -*- coding: utf-8 -*-
import re
from pathlib import Path
from typing import Dict, List, Tuple

ROM_DIACRITICS_MAP = str.maketrans({
    "ă": "a", "â": "a", "î": "i", "ș": "s", "ş": "s", "ț": "t", "ţ": "t",
    "Ă": "A", "Â": "A", "Î": "I", "Ș": "S", "Ş": "S", "Ț": "T", "Ţ": "T",
})

def ensure_user_data(user_data_dir: Path):
    user_data_dir.mkdir(exist_ok=True)
    (user_data_dir / "dictionaries").mkdir(exist_ok=True)
    (user_data_dir / "outputs").mkdir(exist_ok=True)
    # fișiere default
    if not (user_data_dir / "glossary.txt").exists():
        (user_data_dir / "glossary.txt").write_text("", encoding="utf-8")
    if not (user_data_dir / "rules.txt").exists():
        (user_data_dir / "rules.txt").write_text("", encoding="utf-8")

def _read_lines(path: Path) -> List[str]:
    if not path.exists():
        return []
    txt = path.read_text(encoding="utf-8", errors="ignore")
    lines = []
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines

def save_glossary_text(user_data_dir: Path, text: str):
    ensure_user_data(user_data_dir)
    (user_data_dir / "glossary.txt").write_text(text.strip() + ("\n" if text.strip() else ""), encoding="utf-8")

def save_rules_text(user_data_dir: Path, text: str):
    ensure_user_data(user_data_dir)
    (user_data_dir / "rules.txt").write_text(text.strip() + ("\n" if text.strip() else ""), encoding="utf-8")

def import_dictionary_file(user_data_dir: Path, src_path: str) -> str:
    ensure_user_data(user_data_dir)
    src = Path(src_path)
    name = src.name
    dest = user_data_dir / "dictionaries" / name
    dest.write_text(src.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
    return name

def load_enabled_dictionary_files(user_data_dir: Path) -> List[str]:
    ensure_user_data(user_data_dir)
    # simplu: toate .txt din dictionaries
    return sorted([p.name for p in (user_data_dir / "dictionaries").glob("*.txt")])

def load_glossary_terms(user_data_dir: Path) -> List[str]:
    ensure_user_data(user_data_dir)
    return _read_lines(user_data_dir / "glossary.txt")

def load_rules_pairs(user_data_dir: Path) -> List[Tuple[str, str]]:
    ensure_user_data(user_data_dir)
    pairs: List[Tuple[str, str]] = []
    for line in _read_lines(user_data_dir / "rules.txt"):
        # acceptăm "a => b" sau "a->b"
        if "=>" in line:
            a, b = line.split("=>", 1)
        elif "->" in line:
            a, b = line.split("->", 1)
        else:
            continue
        a = a.strip()
        b = b.strip()
        if a and b:
            pairs.append((a, b))
    # prioritate: fraze mai lungi primele
    pairs.sort(key=lambda x: len(x[0]), reverse=True)
    return pairs

def add_rule_pair(user_data_dir: Path, wrong: str, right: str):
    ensure_user_data(user_data_dir)
    path = user_data_dir / "rules.txt"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    line = f"{wrong} => {right}\n"
    if line not in existing:
        path.write_text(existing + line, encoding="utf-8")

def _norm_no_diacritics(s: str) -> str:
    return s.translate(ROM_DIACRITICS_MAP)

def _regex_escape_keep_spaces(s: str) -> str:
    # escape, dar păstrează spațiile ca \s+
    parts = [re.escape(p) for p in s.split()]
    return r"\s+".join(parts)

def autocorrect_from_terms(text: str, terms: List[str]) -> str:
    """
    Autocorrect simplu:
    - pentru fiecare termen/frază cu diacritice, înlocuiește varianta fără diacritice (și/sau cu spații multiple) cu forma corectă.
    - case-insensitive, cu word-boundaries pentru termeni (unde e posibil).
    """
    if not text or not terms:
        return text

    # termeni mai lungi întâi
    terms_sorted = sorted([t.strip() for t in terms if t.strip()], key=len, reverse=True)

    out = text
    for canon in terms_sorted:
        plain = _norm_no_diacritics(canon)
        if plain == canon:
            # dacă nu are diacritice, tot îl folosim ca "stabilizare" a spațiilor (opțional)
            continue

        pattern = _regex_escape_keep_spaces(plain)
        # word boundaries ajută pentru cuvinte, dar pentru fraze poate fi prea strict; folosim \b la capete
        rx = re.compile(rf"\b{pattern}\b", flags=re.IGNORECASE)
        out = rx.sub(canon, out)

    return out

def apply_rules(text: str, pairs: List[Tuple[str, str]]) -> str:
    if not text or not pairs:
        return text
    out = text
    for wrong, right in pairs:
        # înlocuire robustă (fraze + cuvinte), case-sensitive (ca să nu strice acronimele); utilizatorul poate pune ambele cazuri dacă vrea
        # dacă vrei case-insensitive, poți scrie două reguli (ex: "chisinau" și "Chisinau")
        out = out.replace(wrong, right)
    return out

def apply_corrections_to_segments(
    segments: List[Dict],
    user_data_dir: Path,
    enable_dict_autocorrect: bool = True,
    enable_rules: bool = True,
) -> List[Dict]:
    ensure_user_data(user_data_dir)

    glossary = load_glossary_terms(user_data_dir)
    dict_files = load_enabled_dictionary_files(user_data_dir)
    dict_terms: List[str] = []
    for fn in dict_files:
        dict_terms.extend(_read_lines(user_data_dir / "dictionaries" / fn))

    terms = []
    # glosar + dicționare
    if enable_dict_autocorrect:
        terms = glossary + dict_terms

    pairs = load_rules_pairs(user_data_dir) if enable_rules else []

    corrected: List[Dict] = []
    for s in segments:
        txt = (s.get("text") or "")
        if terms:
            txt = autocorrect_from_terms(txt, terms)
        if pairs:
            txt = apply_rules(txt, pairs)
        d = dict(s)
        d["text"] = txt
        corrected.append(d)

    return corrected
