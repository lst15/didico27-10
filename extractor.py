#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Extrai fichas de beneficiários filtrando por números de telefone.
Agora com interface gráfica (tkinter) para escolher:
 - Arquivo de dados (antes --dados)
 - Arquivo de números (antes --numeros)
 - Pasta de saída (antes --saida)

Gera:
  saida/dados.csv
  saida/subsets/cpf_telefone_nome.csv
  saida/subsets/nascimento_agencia_conta.csv
  saida/subsets/endereco.csv
"""

import csv
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Dict, List, Tuple, Iterable, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext


# ------------------------- Logging infra -------------------------

class UILogger:
    def __init__(self, widget: scrolledtext.ScrolledText):
        self.widget = widget

    def write(self, text: str) -> None:
        self.widget.configure(state="normal")
        self.widget.insert(tk.END, text + "\n")
        self.widget.see(tk.END)
        self.widget.configure(state="disabled")
        self.widget.update_idletasks()

    def log(self, msg: str) -> None:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self.write(f"[{ts}] {msg}")


class CLILogger:
    def log(self, msg: str) -> None:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] {msg}")


LOGGER: Optional[object] = None


def log(msg: str) -> None:
    global LOGGER
    if LOGGER is None:
        CLILogger().log(msg)
    else:
        LOGGER.log(msg)


# ------------------------- Utilidades -------------------------

def strip_accents(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode("ASCII")


def norm_key(k: str) -> str:
    k = k.strip()
    k = strip_accents(k).lower()
    k = re.sub(r"[\s_/.-]+", " ", k).strip()
    synonyms = {
        "nome completo": "nome",
        "nome do cliente": "nome",
        "cpf/cnpj": "cpf",
        "cpf cnpj": "cpf",
        "doc": "cpf",
        "documento": "cpf",
        "nascimento": "data nascimento",
        "data de nascimento": "data nascimento",
        "dt nascimento": "data nascimento",
        "telefone fixo": "telefone",
        "celular": "telefone",
        "telefone(s)": "telefone",
        "telefones": "telefone",
        "fone": "telefone",
        "agencia": "agencia",
        "agencia bancaria": "agencia",
        "conta corrente": "conta",
        "n conta": "conta",
        "n da conta": "conta",
        "endereco": "endereco",
        "logradouro": "endereco",
        "rua": "endereco",
        "bairro": "bairro",
        "cidade": "cidade",
        "estado": "estado",
        "uf": "estado",
        "cep": "cep",
    }
    return synonyms.get(k, k)


CANON_LABELS = {
    "nome": "Nome",
    "cpf": "CPF",
    "data nascimento": "Data de Nascimento",
    "telefone": "Telefone",
    "agencia": "Agência",
    "conta": "Conta",
    "endereco": "Endereço",
    "bairro": "Bairro",
    "cidade": "Cidade",
    "estado": "Estado",
    "cep": "CEP",
}

PREFERRED_ORDER = [
    "nome",
    "cpf",
    "data nascimento",
    "telefone",
    "agencia",
    "conta",
    "endereco",
    "bairro",
    "cidade",
    "estado",
    "cep",
]

PIPE_ORDER_KEYS = [
    "cpf","nome","data_nascimento","beneficio","banco_agencia","banco_conta","bairro",
    "banco_codigo","cep","especie","logradouro","municipio","nome_mae","numero_residencia",
    "phones","rg","uf","valor_beneficio"
]
PIPE_ORDER_LABELS = [
    "cpf","nome","data_nascimento","beneficio","banco_agencia","banco_conta","bairro",
    "banco_codigo","cep","especie","logradouro","municipio","nome_mae","numero_residencia",
    "phones","rg","uf","valor_beneficio"
]

KEY_VAL_RE = re.compile(r"^\s*([A-Za-zÀ-ÿ0-9 _\-/().]+?)\s*[:\-–]\s*(.*?)\s*$")

PHONE_RE = re.compile(r"""
    (?:
        (?:\+?55)?
        [\s()-]*
        (?:\d{2})?
        [\s()-]*
    )
    (?:9?\d{4})
    [\s()-]*
    \d{4}
""", re.VERBOSE)

DIGITS_RE = re.compile(r"\d+")


def only_digits(s: str) -> str:
    return "".join(DIGITS_RE.findall(s))


def normalize_phone_digits(d: str) -> str:
    d = only_digits(d)
    if d.startswith("55") and len(d) >= 12:
        d = d[2:]
    if len(d) > 11:
        d = d[-11:]
    return d


def humanize_digits(d: str) -> str:
    if len(d) == 11:
        return f"({d[0:2]}) {d[2]}{d[3:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[0:2]}) {d[2:6]}-{d[6:]}"
    return d


# ------------------------- Parser -------------------------

def split_blocks(lines: List[str]) -> List[List[str]]:
    blocks: List[List[str]] = []
    buf: List[str] = []
    for line in lines:
        if line.strip() == "":
            if buf:
                blocks.append(buf)
                buf = []
        else:
            buf.append(line.rstrip("\n"))
    if buf:
        blocks.append(buf)
    return blocks


def parse_block(block: List[str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    campos: Dict[str, str] = {}
    extras: Dict[str, str] = {}

    for raw in block:
        m = KEY_VAL_RE.match(raw)
        if m:
            raw_key, value = m.group(1).strip(), m.group(2).strip()
            nk = norm_key(raw_key)
            if nk in CANON_LABELS:
                label = CANON_LABELS[nk]
                if label in campos and value:
                    campos[label] = f"{campos[label]} | {value}"
                else:
                    campos[label] = value
            else:
                if raw_key not in extras:
                    extras[raw_key] = value
                elif value:
                    extras[raw_key] = f"{extras[raw_key]} | {value}"

    phones = PHONE_RE.findall("\n".join(block))
    phones_norm = []
    for p in phones:
        pd = normalize_phone_digits(p)
        if pd and pd not in phones_norm:
            phones_norm.append(pd)
    if phones_norm:
        campos.setdefault(
            CANON_LABELS["telefone"],
            " | ".join(humanize_digits(d) for d in phones_norm)
        )

    return campos, extras


def parse_pipe_line(line: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    parts = [p.strip() for p in line.strip().split("|")]
    while len(parts) < len(PIPE_ORDER_KEYS):
        parts.append("")
    parts = parts[:len(PIPE_ORDER_KEYS)]

    campos: Dict[str, str] = {}
    extras: Dict[str, str] = {}

    for key, val in zip(PIPE_ORDER_KEYS, parts):
        if val:
            campos[key] = val

    if campos.get("phones"):
        raw = campos["phones"]
        toks = [t.strip() for t in re.split(r"[;,/]|[\s]+", raw) if t.strip()]
        unique = []
        for t in toks:
            nd = normalize_phone_digits(t)
            if nd and nd not in unique:
                unique.append(nd)
        if unique:
            campos["phones"] = " | ".join(humanize_digits(d) for d in unique)
        else:
            campos["phones"] = raw

    return campos, extras


def looks_like_pipe_format(lines: List[str]) -> bool:
    non_empty = [ln for ln in lines if ln.strip()]
    if not non_empty:
        return False
    hits = 0
    sample = non_empty[:200]
    for ln in sample:
        if ln.count("|") >= (len(PIPE_ORDER_KEYS) - 1):
            hits += 1
    return hits >= max(1, int(0.6 * len(sample)))


# ------------------------- IO -------------------------

def load_targets(path: Path) -> List[str]:
    log(f"Lendo números-alvo: {path}")
    targets: List[str] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        d = normalize_phone_digits(line)
        if d:
            targets.append(d)
    seen = set()
    uniq = []
    for t in targets:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    log(f"Números válidos carregados: {len(uniq)}")
    return uniq


def read_dados(path: Path) -> Tuple[List[Tuple[Dict[str, str], Dict[str, str]]], bool]:
    log(f"Lendo arquivo de dados: {path}")
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    pipe_mode = looks_like_pipe_format(lines)
    if pipe_mode:
        log("Formato detectado: linhas pipe-delimited (formato solicitado).")
        parsed = [parse_pipe_line(ln) for ln in lines if ln.strip()]
        log(f"Registros parseados (pipe): {len(parsed)}")
        return parsed, True

    log("Formato detectado: blocos 'Campo: valor'.")
    blocks = split_blocks(lines)
    log(f"Blocos detectados: {len(blocks)}")
    parsed = [parse_block(b) for b in blocks]
    log(f"Registros parseados (blocos): {len(parsed)}")
    return parsed, False


# ------------------------- Seleção por telefone -------------------------

def record_phone_digits(rec_campos: Dict[str, str]) -> List[str]:
    candidates = []
    if "phones" in rec_campos and rec_campos["phones"]:
        candidates.append(rec_campos["phones"])
    tel_label = CANON_LABELS["telefone"]
    if tel_label in rec_campos and rec_campos[tel_label]:
        candidates.append(rec_campos[tel_label])
    text = "\n".join(candidates)
    seen = set()
    out: List[str] = []
    for m in PHONE_RE.findall(text):
        nd = normalize_phone_digits(m)
        if nd and nd not in seen:
            seen.add(nd)
            out.append(nd)
    return out


def choose_occurrence_number(rec_digits: List[str], targets_ordered: List[str]) -> Optional[str]:
    rec_set = set(rec_digits)
    for t in targets_ordered:
        if t in rec_set:
            return t
    return None


def filter_records_by_targets(parsed, targets):
    log("Filtrando registros por números-alvo...")
    out = []
    for (campos, extras) in parsed:
        digits = record_phone_digits(campos)
        occ = choose_occurrence_number(digits, targets)
        if occ is not None:
            out.append((campos, extras, occ))
    log(f"Registros correspondentes: {len(out)}")
    return out


# ------------------------- Escrita CSV -------------------------

def collect_headers(records, fallback):
    base = records if records else fallback
    headers: List[str] = []

    def add(h):
        if h not in headers:
            headers.append(h)

    for canon in PREFERRED_ORDER:
        label = CANON_LABELS.get(canon)
        if label and any(label in campos for campos, _ in base):
            add(label)

    for campos, extras in base:
        for k in extras.keys():
            add(k)

    log(f"Cabeçalhos coletados: {headers}")
    return headers


def write_csv(path: Path, headers: List[str], rows: List[Dict[str, str]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    log(f"Gravando CSV: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers, delimiter=';')
        w.writeheader()
        for r in rows:
            w.writerow({h: r.get(h, "sem dados") or "sem dados" for h in headers})


# ------------------------- Core pipeline -------------------------

def run_pipeline(dados_file: Path, numeros_file: Path, out_dir: Path):
    if not dados_file.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {dados_file}")
    if not numeros_file.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {numeros_file}")

    log("Inicializando pipeline...")

    targets = load_targets(numeros_file)
    if not targets:
        raise RuntimeError("Nenhum número válido encontrado no arquivo de números.")

    parsed, pipe_mode = read_dados(dados_file)
    if not parsed:
        raise RuntimeError("Nenhum registro encontrado no arquivo de dados.")

    log("Exemplo de 3 números-alvo:")
    log(str(targets[:3]))
    if parsed:
        exemplo = record_phone_digits(parsed[0][0])
        log("Telefones do primeiro registro parseado (normalizados):")
        log(str(exemplo))

    selected = filter_records_by_targets(parsed, targets)

    rows_full: List[Dict[str, str]] = []

    if pipe_mode:
        headers = PIPE_ORDER_LABELS.copy()
        for campos, extras, occ in selected:
            row = {}
            for key in PIPE_ORDER_KEYS:
                if key == "phones":
                    row["phones"] = humanize_digits(occ) if occ else (
                        campos.get("phones", "sem dados") or "sem dados"
                    )
                else:
                    row[key] = campos.get(key, "sem dados") or "sem dados"
            rows_full.append(row)
        write_csv(out_dir / "dados.csv", headers, rows_full)
    else:
        headers = collect_headers([(c, e) for (c, e, _) in selected], parsed)
        tel_label = CANON_LABELS["telefone"]
        for campos, extras, occ in selected:
            row = {}
            for h in headers:
                if h in campos:
                    row[h] = campos[h]
                elif h in extras:
                    row[h] = extras[h]
                else:
                    row[h] = "sem dados"
            row[tel_label] = humanize_digits(occ) if occ else "sem dados"
            rows_full.append(row)
        write_csv(out_dir / "dados.csv", headers, rows_full)

    subsets_dir = out_dir / "subsets"

    rows_subset_1: List[Dict[str, str]] = []
    for campos, extras, occ in selected:
        cpf_val = (
            campos.get("cpf")
            or campos.get(CANON_LABELS.get("cpf"))
            or campos.get("CPF")
            or campos.get("cpf".upper(), "sem dados")
        )
        nome_val = (
            campos.get("nome")
            or campos.get(CANON_LABELS.get("nome"))
            or campos.get("Nome", "sem dados")
        )
        rows_subset_1.append({
            "CPF": cpf_val or "sem dados",
            "Telefone": humanize_digits(occ) if occ else "sem dados",
            "Nome": nome_val or "sem dados",
        })
    write_csv(subsets_dir / "cpf_telefone_nome.csv",
              ["CPF", "Telefone", "Nome"],
              rows_subset_1)

    rows_subset_2: List[Dict[str, str]] = []
    for campos, extras, occ in selected:
        rows_subset_2.append({
            CANON_LABELS["data nascimento"]: (
                campos.get(CANON_LABELS["data nascimento"], campos.get("data_nascimento", "sem dados"))
                or "sem dados"
            ),
            CANON_LABELS["agencia"]: (
                campos.get(CANON_LABELS["agencia"], campos.get("banco_agencia", "sem dados"))
                or "sem dados"
            ),
            CANON_LABELS["conta"]: (
                campos.get(CANON_LABELS["conta"], campos.get("banco_conta", "sem dados"))
                or "sem dados"
            ),
        })
    write_csv(subsets_dir / "nascimento_agencia_conta.csv",
              [CANON_LABELS["data nascimento"], CANON_LABELS["agencia"], CANON_LABELS["conta"]],
              rows_subset_2)

    rows_subset_3: List[Dict[str, str]] = []
    for campos, extras, occ in selected:
        endereco_val = (
            campos.get(CANON_LABELS.get("endereco"))
            or campos.get("logradouro")
            or campos.get("endereco")
            or "sem dados"
        )
        rows_subset_3.append({
            CANON_LABELS["endereco"]: endereco_val,
        })
    write_csv(subsets_dir / "endereco.csv",
              [CANON_LABELS["endereco"]],
              rows_subset_3)

    log(f"Registros lidos: {len(parsed)}")
    log(f"Alvos (números): {len(targets)}")
    log(f"Registros selecionados: {len(selected)}")
    log(f"Saída: {out_dir.resolve()}")
    log("Concluído.")


# ------------------------- GUI -------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Extrator de Dados por Telefone")
        self.geometry("900x560")
        self.minsize(750, 450)
        self.rowconfigure(1, weight=1)      # área do log cresce
        self.columnconfigure(0, weight=1)   # frame principal ocupa largura

        # paths
        self.dados_path_var = tk.StringVar()
        self.numeros_path_var = tk.StringVar()
        self.saida_dir_var = tk.StringVar()

        # --- Frame de inputs (grid responsivo) ---
        frm = tk.Frame(self, padx=10, pady=10)
        frm.grid(row=0, column=0, sticky="ew")
        frm.columnconfigure(1, weight=1)  # coluna da Entry se expande

        # Linha: Arquivo de dados
        tk.Label(frm, text="Arquivo de dados (txt):").grid(row=0, column=0, sticky="w", pady=(0,4))
        tk.Entry(frm, textvariable=self.dados_path_var) \
            .grid(row=0, column=1, sticky="ew", padx=(0,6), pady=(0,4))
        tk.Button(frm, text="Selecionar...", command=self.pick_dados, width=14) \
            .grid(row=0, column=2, sticky="w", pady=(0,4))

        # Linha: Arquivo de números
        tk.Label(frm, text="Arquivo de números (txt):").grid(row=1, column=0, sticky="w", pady=(0,4))
        tk.Entry(frm, textvariable=self.numeros_path_var) \
            .grid(row=1, column=1, sticky="ew", padx=(0,6), pady=(0,4))
        tk.Button(frm, text="Selecionar...", command=self.pick_numeros, width=14) \
            .grid(row=1, column=2, sticky="w", pady=(0,4))

        # Linha: Pasta de saída
        tk.Label(frm, text="Pasta de saída:").grid(row=2, column=0, sticky="w", pady=(0,6))
        tk.Entry(frm, textvariable=self.saida_dir_var) \
            .grid(row=2, column=1, sticky="ew", padx=(0,6), pady=(0,6))
        tk.Button(frm, text="Selecionar...", command=self.pick_saida, width=14) \
            .grid(row=2, column=2, sticky="w", pady=(0,6))

        # Botão executar (ocupa as 3 colunas)
        tk.Button(frm, text="EXECUTAR", bg="#222", fg="#fff", command=self.execute) \
            .grid(row=3, column=0, columnspan=3, sticky="we", pady=(8,0))

        # --- Log ---
        log_frame = tk.LabelFrame(self, text="Log", padx=5, pady=5)
        log_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(10,10))
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log_box = scrolledtext.ScrolledText(
            log_frame, wrap=tk.WORD, state="disabled", font=("Courier New", 9)
        )
        self.log_box.grid(row=0, column=0, sticky="nsew")

        # logger UI
        global LOGGER
        LOGGER = UILogger(self.log_box)
        log("Pronto. Selecione os arquivos e execute.")

    def pick_dados(self):
        path = filedialog.askopenfilename(
            title="Selecione o arquivo de dados",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if path:
            self.dados_path_var.set(path)

    def pick_numeros(self):
        path = filedialog.askopenfilename(
            title="Selecione o arquivo de números (um por linha)",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if path:
            self.numeros_path_var.set(path)

    def pick_saida(self):
        path = filedialog.askdirectory(title="Selecione a pasta de saída")
        if path:
            self.saida_dir_var.set(path)

    def execute(self):
        dados_path = self.dados_path_var.get().strip()
        numeros_path = self.numeros_path_var.get().strip()
        saida_dir = self.saida_dir_var.get().strip()

        if not dados_path or not numeros_path or not saida_dir:
            messagebox.showerror("Erro", "Preencha todos os campos.")
            return

        try:
            run_pipeline(Path(dados_path), Path(numeros_path), Path(saida_dir))
            messagebox.showinfo("Concluído", "Processamento finalizado sem erro.")
        except Exception as e:
            log(f"ERRO: {e}")
            messagebox.showerror("Erro", str(e))


def main():
    try:
        app = App()
        app.mainloop()
    except tk.TclError as exc:
        print("Erro de interface gráfica (provavelmente ambiente sem display):", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
