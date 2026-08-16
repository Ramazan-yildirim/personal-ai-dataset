"""Single-window local UI for the personal dataset pipeline."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


from src.database.migrations import initialize_core_database
from src.database.persons import create_person, list_persons
from src.database.facts import (
    correct_fact,
    get_fact,
    get_fact_corrections,
    list_facts,
    soft_delete_fact,
    supersede_fact,
)
from src.database.sources import add_source, deactivate_source, list_sources
from src.database.staging_connection import initialize_staging_database
from src.exporters.common import load_export_facts
from src.exporters.datasets import export_all_datasets
from src.extraction.candidate_import import import_candidate_bundle
from src.extraction.documents import extract_source
from src.ingestion.documents import ingest_document
from src.validation.candidates import (
    CandidateValidationFailedError,
    approve_candidate,
    create_candidate,
    list_candidates,
    reject_candidate,
    validate_candidate,
)


SEPARATOR = " — "
NO_SOURCE = "Kaynak yok"
VISIBILITIES = ("public", "private", "internal")


def optional_text(value: str) -> str | None:
    value = value.strip()
    return value or None


def choice_id(value: str, *, allow_none: bool = False) -> int | None:
    value = value.strip()
    if allow_none and (not value or value == NO_SOURCE):
        return None
    raw_id = value.split(SEPARATOR, 1)[0]
    if not raw_id.isdigit() or int(raw_id) <= 0:
        raise ValueError("Lütfen listeden geçerli bir kayıt seçin.")
    return int(raw_id)


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


class FactCorrectionDialog(simpledialog.Dialog):
    """Edit all correctable fact fields without changing untouched metadata."""

    def __init__(self, parent: tk.Misc, fact: dict[str, Any]):
        self.fact = fact
        self.variables = {
            "category": tk.StringVar(value=fact["category"]),
            "key": tk.StringVar(value=fact["key"]),
            "value": tk.StringVar(value=fact["value"]),
            "valid_from": tk.StringVar(value=fact["valid_from"] or ""),
            "valid_to": tk.StringVar(value=fact["valid_to"] or ""),
            "visibility": tk.StringVar(value=fact["visibility"]),
            "confidence": tk.StringVar(value=str(fact["confidence"])),
            "correction_note": tk.StringVar(),
        }
        self.allow_overlap = tk.BooleanVar(value=False)
        self.result: dict[str, Any] | None = None
        super().__init__(parent, title=f"Fact #{fact['id']} alanlarını düzelt")

    def body(self, master: tk.Misc):
        ttk.Label(
            master,
            text=(
                "Yalnızca değiştirdiğiniz alanlar audit kaydına yazılır. "
                "Tarih alanını boş bırakmak tarihi temizler."
            ),
            foreground="#475569",
            wraplength=500,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        labels = (
            ("Kategori", "category"),
            ("Anahtar", "key"),
            ("Değer", "value"),
            ("Başlangıç tarihi (YYYY-MM-DD)", "valid_from"),
            ("Bitiş tarihi (YYYY-MM-DD)", "valid_to"),
            ("Görünürlük", "visibility"),
            ("Confidence (0.0-1.0)", "confidence"),
            ("Düzeltme nedeni", "correction_note"),
        )
        first_entry = None
        for row, (label, field_name) in enumerate(labels, start=1):
            ttk.Label(master, text=label).grid(
                row=row,
                column=0,
                sticky="w",
                padx=(0, 10),
                pady=4,
            )
            if field_name == "visibility":
                widget = ttk.Combobox(
                    master,
                    textvariable=self.variables[field_name],
                    values=VISIBILITIES,
                    state="readonly",
                )
            else:
                widget = ttk.Entry(
                    master,
                    textvariable=self.variables[field_name],
                    width=48,
                )
            widget.grid(row=row, column=1, sticky="ew", pady=4)
            if first_entry is None:
                first_entry = widget
        ttk.Checkbutton(
            master,
            text="Bu anahtar aynı dönemde birden çok değere sahip olabilir",
            variable=self.allow_overlap,
        ).grid(
            row=len(labels) + 1,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(8, 0),
        )
        master.columnconfigure(1, weight=1)
        return first_entry

    def validate(self) -> bool:
        note = self.variables["correction_note"].get().strip()
        if not note:
            messagebox.showerror(
                "Eksik bilgi",
                "Audit için düzeltme nedeni zorunludur.",
                parent=self,
            )
            return False
        try:
            confidence = float(self.variables["confidence"].get())
        except ValueError:
            messagebox.showerror(
                "Geçersiz confidence",
                "Confidence 0.0 ile 1.0 arasında sayı olmalıdır.",
                parent=self,
            )
            return False
        if not 0.0 <= confidence <= 1.0:
            messagebox.showerror(
                "Geçersiz confidence",
                "Confidence 0.0 ile 1.0 arasında olmalıdır.",
                parent=self,
            )
            return False
        return True

    def apply(self) -> None:
        self.result = {
            "category": self.variables["category"].get(),
            "key": self.variables["key"].get(),
            "value": self.variables["value"].get(),
            "valid_from": optional_text(self.variables["valid_from"].get()),
            "valid_to": optional_text(self.variables["valid_to"].get()),
            "visibility": self.variables["visibility"].get(),
            "confidence": float(self.variables["confidence"].get()),
            "correction_note": self.variables["correction_note"].get(),
            "allow_overlap": self.allow_overlap.get(),
        }


class PersonalDatasetApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Personal AI Dataset — Kontrol Merkezi")
        self.geometry("1180x760")
        self.minsize(980, 650)
        self.people: list[dict[str, Any]] = []
        self.sources: list[dict[str, Any]] = []
        self.candidates: dict[int, dict[str, Any]] = {}
        self._style()
        self._build()
        self.after(0, self.refresh_all)

    def _style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Treeview", rowheight=26)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        style.configure("Title.TLabel", font=("Segoe UI", 17, "bold"))
        style.configure("Section.TLabel", font=("Segoe UI", 11, "bold"))

    def _build(self) -> None:
        header = ttk.Frame(self, padding=(16, 12))
        header.pack(fill="x")
        ttk.Label(
            header,
            text="Personal AI Dataset — Yerel Kontrol Merkezi",
            style="Title.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            header,
            text=(
                "Belge veya manuel bilgi → Candidate → Validate → "
                "Senin onayın → Core DB → Export"
            ),
            foreground="#475569",
        ).pack(anchor="w", pady=(3, 0))
        ttk.Label(
            header,
            text="Onaylanmayan hiçbir candidate core veritabanına geçmez.",
            foreground="#9a3412",
        ).pack(anchor="w", pady=(3, 0))

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=12, pady=8)
        self.people_tab = ttk.Frame(notebook, padding=12)
        self.documents_tab = ttk.Frame(notebook, padding=12)
        self.review_tab = ttk.Frame(notebook, padding=12)
        self.export_tab = ttk.Frame(notebook, padding=12)
        notebook.add(self.people_tab, text="Kişiler ve Manuel Bilgi")
        notebook.add(self.documents_tab, text="Belgeler")
        notebook.add(self.review_tab, text="Onay Merkezi")
        notebook.add(self.export_tab, text="Export")
        self._build_people()
        self._build_documents()
        self._build_review()
        self._build_export()

        self.status_var = tk.StringVar(value="Hazırlanıyor...")
        ttk.Label(
            self,
            textvariable=self.status_var,
            anchor="w",
            padding=(12, 5),
        ).pack(fill="x")

    def _tree(
        self,
        parent: tk.Misc,
        columns: tuple[tuple[str, str, int], ...],
        *,
        height: int,
    ) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        keys = tuple(column[0] for column in columns)
        tree = ttk.Treeview(frame, columns=keys, show="headings", height=height)
        for key, title, width in columns:
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=45)
        vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(
            yscrollcommand=vertical.set,
            xscrollcommand=horizontal.set,
        )
        tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return tree

    def _build_people(self) -> None:
        person = ttk.LabelFrame(self.people_tab, text="Kişi", padding=10)
        person.pack(fill="x")
        self.person_name = tk.StringVar()
        self.person_choice = tk.StringVar()
        ttk.Label(person, text="Yeni kişi").grid(row=0, column=0, sticky="w")
        ttk.Entry(person, textvariable=self.person_name, width=30).grid(
            row=1, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Button(person, text="Oluştur", command=self.add_person).grid(
            row=1, column=1, padx=(0, 18)
        )
        ttk.Label(person, text="Çalışılan kişi").grid(
            row=0, column=2, sticky="w"
        )
        self.person_combo = ttk.Combobox(
            person,
            textvariable=self.person_choice,
            state="readonly",
            width=38,
        )
        self.person_combo.grid(row=1, column=2, sticky="ew")
        self.person_combo.bind("<<ComboboxSelected>>", self.refresh_facts)
        person.columnconfigure(0, weight=1)
        person.columnconfigure(2, weight=1)

        form = ttk.LabelFrame(
            self.people_tab,
            text="Manuel bilgi — önce candidate olarak kaydedilir",
            padding=10,
        )
        form.pack(fill="x", pady=10)
        self.c_category = tk.StringVar()
        self.c_key = tk.StringVar()
        self.c_value = tk.StringVar()
        self.c_from = tk.StringVar()
        self.c_to = tk.StringVar()
        self.c_visibility = tk.StringVar(value="private")
        self.c_confidence = tk.StringVar(value="1.0")
        self.c_source = tk.StringVar(value=NO_SOURCE)
        self.c_overlap = tk.BooleanVar(value=False)
        fields = (
            ("Kategori", self.c_category),
            ("Anahtar", self.c_key),
            ("Değer", self.c_value),
            ("Başlangıç", self.c_from),
            ("Bitiş", self.c_to),
        )
        for index, (label, variable) in enumerate(fields):
            ttk.Label(form, text=label).grid(
                row=0, column=index, sticky="w", padx=3
            )
            ttk.Entry(form, textvariable=variable, width=18).grid(
                row=1, column=index, sticky="ew", padx=3
            )
            form.columnconfigure(index, weight=1)
        ttk.Label(form, text="Kaynak").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.source_combo = ttk.Combobox(
            form,
            textvariable=self.c_source,
            state="readonly",
        )
        self.source_combo.grid(row=3, column=0, columnspan=2, sticky="ew", padx=3)
        ttk.Label(form, text="Görünürlük").grid(
            row=2, column=2, sticky="w", pady=(8, 0)
        )
        ttk.Combobox(
            form,
            textvariable=self.c_visibility,
            values=VISIBILITIES,
            state="readonly",
        ).grid(row=3, column=2, sticky="ew", padx=3)
        ttk.Label(form, text="Confidence").grid(
            row=2, column=3, sticky="w", pady=(8, 0)
        )
        ttk.Spinbox(
            form,
            textvariable=self.c_confidence,
            from_=0.0,
            to=1.0,
            increment=0.1,
        ).grid(row=3, column=3, sticky="ew", padx=3)
        ttk.Checkbutton(
            form,
            text="Çok değerli",
            variable=self.c_overlap,
        ).grid(row=3, column=4)
        ttk.Button(
            form,
            text="Candidate kaydet",
            command=self.add_manual_candidate,
        ).grid(row=4, column=4, sticky="e", pady=(8, 0))

        ttk.Label(
            self.people_tab,
            text="Onaylanmış aktif fact'ler",
            style="Section.TLabel",
        ).pack(anchor="w", pady=(6, 5))
        fact_actions = ttk.LabelFrame(
            self.people_tab,
            text="Seçili bilgi işlemleri",
            padding=7,
        )
        fact_actions.pack(fill="x", pady=(0, 6))
        ttk.Button(
            fact_actions,
            text="Alanları düzelt",
            command=self.edit_selected_fact,
        ).pack(side="left")
        ttk.Button(
            fact_actions,
            text="Yeni sürüm oluştur",
            command=self.supersede_selected_fact,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            fact_actions,
            text="Sil (audit kaydı korunur)",
            command=self.delete_selected_fact,
        ).pack(side="left", padx=6)
        ttk.Button(
            fact_actions,
            text="Düzeltme geçmişi",
            command=self.show_selected_fact_corrections,
        ).pack(side="left")
        self.show_fact_history = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            fact_actions,
            text="Tarihçe ve silinenleri göster",
            variable=self.show_fact_history,
            command=self.refresh_facts,
        ).pack(side="right")
        self.facts_tree = self._tree(
            self.people_tab,
            (
                ("id", "ID", 50),
                ("category", "Kategori", 110),
                ("key", "Anahtar", 140),
                ("value", "Değer", 310),
                ("visibility", "Görünürlük", 90),
                ("status", "Durum", 80),
                ("valid_from", "Başlangıç", 100),
                ("valid_to", "Bitiş", 100),
            ),
            height=11,
        )

    def _build_documents(self) -> None:
        form = ttk.LabelFrame(self.documents_tab, text="Belge ekle", padding=10)
        form.pack(fill="x")
        self.d_type = tk.StringVar(value="other")
        self.d_title = tk.StringVar()
        self.d_path = tk.StringVar()
        self.d_date = tk.StringVar()
        values = (
            ("Tür", self.d_type),
            ("Başlık", self.d_title),
            ("Belge yolu", self.d_path),
            ("Tarih", self.d_date),
        )
        for index, (label, variable) in enumerate(values):
            ttk.Label(form, text=label).grid(row=0, column=index, sticky="w")
            if index == 0:
                widget = ttk.Combobox(
                    form,
                    textvariable=variable,
                    values=("cv", "transcript", "certificate", "github", "portfolio", "other"),
                    state="readonly",
                )
            else:
                widget = ttk.Entry(form, textvariable=variable)
            widget.grid(row=1, column=index, sticky="ew", padx=(0, 6))
            form.columnconfigure(index, weight=2 if index == 2 else 1)
        ttk.Button(form, text="Dosya seç", command=self.choose_document).grid(
            row=1, column=4, padx=(0, 6)
        )
        ttk.Button(form, text="Belgeyi ekle", command=self.add_document).grid(
            row=1, column=5
        )

        manual = ttk.Frame(self.documents_tab)
        manual.pack(fill="x", pady=8)
        self.manual_source_title = tk.StringVar()
        self.manual_source_date = tk.StringVar()
        ttk.Label(manual, text="Dosyasız manuel kaynak:").pack(side="left")
        ttk.Entry(
            manual, textvariable=self.manual_source_title, width=32
        ).pack(side="left", padx=5)
        ttk.Entry(
            manual, textvariable=self.manual_source_date, width=13
        ).pack(side="left", padx=(0, 5))
        ttk.Button(
            manual, text="Oluştur", command=self.add_manual_source
        ).pack(side="left")

        self.sources_tree = self._tree(
            self.documents_tab,
            (
                ("id", "ID", 45),
                ("type", "Tür", 90),
                ("title", "Başlık", 220),
                ("date", "Tarih", 95),
                ("path", "Dosya", 380),
                ("active", "Aktif", 55),
            ),
            height=8,
        )
        tools = ttk.Frame(self.documents_tab)
        tools.pack(fill="x", pady=6)
        ttk.Button(
            tools, text="Metin çıkar", command=self.extract_selected
        ).pack(side="left")
        ttk.Button(
            tools, text="Pasifleştir", command=self.deactivate_selected
        ).pack(side="left", padx=5)
        self.bundle_path = tk.StringVar()
        ttk.Label(tools, text="Candidate bundle:").pack(side="left", padx=(15, 4))
        ttk.Entry(tools, textvariable=self.bundle_path).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(tools, text="Seç", command=self.choose_bundle).pack(
            side="left", padx=5
        )
        ttk.Button(tools, text="Import", command=self.import_bundle).pack(side="left")
        ttk.Label(
            self.documents_tab,
            text="Extraction yalnızca metin çıkarır; otomatik olarak fact oluşturmaz.",
            foreground="#9a3412",
        ).pack(anchor="w")
        self.document_output = tk.Text(
            self.documents_tab, height=8, wrap="word", font=("Consolas", 9)
        )
        self.document_output.pack(fill="both", expand=True, pady=(4, 0))

    def _build_review(self) -> None:
        toolbar = ttk.Frame(self.review_tab)
        toolbar.pack(fill="x", pady=(0, 6))
        self.review_filter = tk.StringVar(value="pending")
        ttk.Label(toolbar, text="Durum:").pack(side="left")
        combo = ttk.Combobox(
            toolbar,
            textvariable=self.review_filter,
            values=("pending", "approved", "rejected", "all"),
            state="readonly",
            width=14,
        )
        combo.pack(side="left", padx=5)
        combo.bind("<<ComboboxSelected>>", self.refresh_candidates)
        ttk.Button(toolbar, text="Yenile", command=self.refresh_candidates).pack(
            side="left"
        )
        self.candidates_tree = self._tree(
            self.review_tab,
            (
                ("id", "ID", 45),
                ("person", "Kişi", 120),
                ("category", "Kategori", 100),
                ("key", "Anahtar", 120),
                ("value", "Değer", 260),
                ("source", "Kaynak", 60),
                ("visibility", "Görünürlük", 80),
                ("validation", "Validasyon", 80),
                ("review", "İnceleme", 80),
            ),
            height=11,
        )
        self.candidates_tree.bind("<<TreeviewSelect>>", self.show_candidate)
        bottom = ttk.Frame(self.review_tab)
        bottom.pack(fill="both", expand=True, pady=(8, 0))
        self.candidate_output = tk.Text(
            bottom, height=10, wrap="word", font=("Consolas", 9)
        )
        self.candidate_output.pack(side="left", fill="both", expand=True)
        actions = ttk.LabelFrame(bottom, text="Karar", padding=10)
        actions.pack(side="left", fill="y", padx=(8, 0))
        self.review_note = tk.StringVar()
        ttk.Label(actions, text="Not").pack(anchor="w")
        ttk.Entry(actions, textvariable=self.review_note, width=30).pack(
            fill="x", pady=(3, 8)
        )
        ttk.Button(
            actions, text="Validate", command=self.validate_selected
        ).pack(fill="x", pady=2)
        ttk.Button(
            actions, text="Onayla → Core DB", command=self.approve_selected
        ).pack(fill="x", pady=2)
        ttk.Button(
            actions, text="Reddet", command=self.reject_selected
        ).pack(fill="x", pady=2)

    def _build_export(self) -> None:
        ttk.Label(
            self.export_tab,
            text=(
                "Onaylanmış güncel bilgiler Transformer, fine-tuning ve RAG "
                "dosyalarına birlikte uygulanır."
            ),
        ).pack(anchor="w")
        ttk.Label(
            self.export_tab,
            text="Hedef: data/exports/",
            foreground="#475569",
        ).pack(anchor="w", pady=(2, 8))
        ttk.Button(
            self.export_tab,
            text="Export",
            command=self.export,
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            self.export_tab,
            text="Güvenlik gereği yalnızca public ve active bilgiler export edilir.",
            foreground="#9a3412",
        ).pack(anchor="w")
        self.export_output = tk.Text(
            self.export_tab, height=20, wrap="word", font=("Consolas", 9)
        )
        self.export_output.pack(fill="both", expand=True, pady=(4, 0))

    @staticmethod
    def _clear(tree: ttk.Treeview) -> None:
        for item in tree.get_children():
            tree.delete(item)

    @staticmethod
    def _set_output(widget: tk.Text, value: Any) -> None:
        widget.delete("1.0", "end")
        widget.insert("1.0", value if isinstance(value, str) else json_text(value))

    @staticmethod
    def _selected_id(tree: ttk.Treeview) -> int:
        selection = tree.selection()
        if not selection:
            raise ValueError("Önce tablodan bir kayıt seçin.")
        return int(tree.item(selection[0], "values")[0])

    def _perform(
        self,
        action: Callable[[], Any],
        success: str,
        *,
        refresh: bool = True,
    ) -> Any | None:
        try:
            result = action()
        except CandidateValidationFailedError as error:
            self.status_var.set("Candidate validasyonu başarısız.")
            messagebox.showerror(
                "Validasyon başarısız",
                json_text(error.issues),
                parent=self,
            )
            self.refresh_candidates()
            return None
        except Exception as error:
            self.status_var.set(f"Hata: {error}")
            messagebox.showerror("İşlem başarısız", str(error), parent=self)
            return None
        if refresh:
            self.refresh_all()
        self.status_var.set(success)
        messagebox.showinfo("Tamamlandı", success, parent=self)
        return result

    def refresh_all(self) -> None:
        try:
            self.people = list_persons()
            self.sources = list_sources()
            pending = list_candidates(review_status="pending")
            facts = load_export_facts(visibilities=VISIBILITIES)
        except Exception as error:
            self.status_var.set(f"Yenileme hatası: {error}")
            messagebox.showerror("Yenileme hatası", str(error), parent=self)
            return

        person_values = [
            f"{item['id']}{SEPARATOR}{item['name']}" for item in self.people
        ]
        self.person_combo["values"] = person_values
        if self.person_choice.get() not in person_values:
            self.person_choice.set(person_values[0] if person_values else "")

        source_values = [NO_SOURCE] + [
            f"{item['id']}{SEPARATOR}{item['title']}"
            for item in self.sources
            if item["is_active"]
        ]
        self.source_combo["values"] = source_values
        if self.c_source.get() not in source_values:
            self.c_source.set(NO_SOURCE)

        self.refresh_facts()
        self.refresh_sources()
        self.refresh_candidates()
        self.status_var.set(
            f"{len(self.people)} kişi • {len(self.sources)} kaynak • "
            f"{len(pending)} onay bekleyen • {len(facts)} aktif fact"
        )

    def refresh_facts(self, _event=None) -> None:
        self._clear(self.facts_tree)
        try:
            person_id = choice_id(self.person_choice.get())
        except ValueError:
            return
        try:
            facts = list_facts(
                person_id,
                include_inactive=self.show_fact_history.get(),
            )
        except Exception as error:
            self.status_var.set(f"Fact yenileme hatası: {error}")
            return
        for fact in facts:
            self.facts_tree.insert(
                "",
                "end",
                values=(
                    fact["id"],
                    fact["category"],
                    fact["key"],
                    fact["value"],
                    fact["visibility"],
                    fact["status"],
                    fact["valid_from"] or "",
                    fact["valid_to"] or "",
                ),
            )

    def refresh_sources(self) -> None:
        self._clear(self.sources_tree)
        for source in self.sources:
            self.sources_tree.insert(
                "",
                "end",
                values=(
                    source["id"],
                    source["source_type"],
                    source["title"],
                    source["source_date"] or "",
                    source["file_path"] or "",
                    "Evet" if source["is_active"] else "Hayır",
                ),
            )

    def refresh_candidates(self, _event=None) -> None:
        self._clear(self.candidates_tree)
        review_status = self.review_filter.get()
        try:
            rows = list_candidates(
                review_status=None if review_status == "all" else review_status
            )
        except Exception as error:
            self.status_var.set(f"Candidate yenileme hatası: {error}")
            return
        self.candidates = {item["id"]: item for item in rows}
        names = {item["id"]: item["name"] for item in self.people}
        for item in rows:
            self.candidates_tree.insert(
                "",
                "end",
                values=(
                    item["id"],
                    names.get(item["person_id"], item["person_id"]),
                    item["category"],
                    item["key"],
                    item["value"],
                    item["source_id"] or "",
                    item["visibility"],
                    item["validation_status"],
                    item["review_status"],
                ),
            )

    def add_person(self) -> None:
        result = self._perform(
            lambda: create_person(self.person_name.get()),
            "Kişi oluşturuldu.",
        )
        if result is not None:
            self.person_name.set("")

    def add_manual_candidate(self) -> None:
        def action():
            return create_candidate(
                choice_id(self.person_choice.get()),
                self.c_category.get(),
                self.c_key.get(),
                self.c_value.get(),
                source_id=choice_id(self.c_source.get(), allow_none=True),
                valid_from=optional_text(self.c_from.get()),
                valid_to=optional_text(self.c_to.get()),
                visibility=self.c_visibility.get(),
                confidence=float(self.c_confidence.get()),
                allow_overlap=self.c_overlap.get(),
            )

        result = self._perform(
            action,
            "Candidate kaydedildi; henüz core veriye eklenmedi.",
        )
        if result is not None:
            self.c_value.set("")

    def edit_selected_fact(self) -> None:
        try:
            fact_id = self._selected_id(self.facts_tree)
            fact = get_fact(fact_id)
            if fact["status"] == "deleted":
                raise ValueError("Deleted bir fact düzeltilemez.")
        except Exception as error:
            messagebox.showerror("Düzeltme yapılamadı", str(error), parent=self)
            return

        dialog = FactCorrectionDialog(self, fact)
        if dialog.result is None:
            return
        if not messagebox.askyesno(
            "Alan düzeltmesini onayla",
            (
                "Yalnızca gerçekten değişen alanlar güncellenecek. Fact ID, "
                "source bağlantıları ve değiştirmediğiniz alanlar korunacak. "
                "Eski/yeni değerler audit kaydına yazılsın mı?"
            ),
            parent=self,
        ):
            return
        result = self._perform(
            lambda: correct_fact(fact_id, **dialog.result),
            "Bilgi alanları düzeltildi ve audit kaydı oluşturuldu.",
        )
        if result is not None:
            self.show_fact_corrections(fact_id)

    def supersede_selected_fact(self) -> None:
        try:
            fact_id = self._selected_id(self.facts_tree)
            fact = get_fact(fact_id)
            if fact["valid_to"] is not None:
                raise ValueError(
                    "Yalnızca açık uçlu güncel bir fact yeni sürümle "
                    "değiştirilebilir."
                )
        except Exception as error:
            messagebox.showerror("Düzenleme yapılamadı", str(error), parent=self)
            return

        new_value = simpledialog.askstring(
            "Yeni değer",
            (
                f"{fact['category']}.{fact['key']} için yeni değeri girin.\n"
                "Kategori ve anahtar değişecekse eski kaydı silip yeni "
                "candidate oluşturun."
            ),
            initialvalue=fact["value"],
            parent=self,
        )
        if new_value is None:
            return
        valid_from = simpledialog.askstring(
            "Yeni sürüm tarihi",
            "Yeni değerin başlangıç tarihi (YYYY-MM-DD):",
            initialvalue=date.today().isoformat(),
            parent=self,
        )
        if valid_from is None:
            return
        previous_valid_to = simpledialog.askstring(
            "Eski sürümün bitişi",
            (
                "Eski değerin bitiş tarihi (YYYY-MM-DD). Boş bırakırsanız "
                "yeni başlangıçtan bir gün önce hesaplanır:"
            ),
            initialvalue="",
            parent=self,
        )
        if previous_valid_to is None:
            return
        visibility = simpledialog.askstring(
            "Görünürlük",
            "Yeni sürüm visibility değeri (public/private/internal):",
            initialvalue=fact["visibility"],
            parent=self,
        )
        if visibility is None:
            return
        if visibility not in VISIBILITIES:
            messagebox.showerror(
                "Geçersiz görünürlük",
                "Visibility public, private veya internal olmalıdır.",
                parent=self,
            )
            return
        confidence = simpledialog.askstring(
            "Confidence",
            "Yeni sürüm confidence değeri (0.0-1.0):",
            initialvalue=str(fact["confidence"]),
            parent=self,
        )
        if confidence is None:
            return

        active_sources = [
            source for source in self.sources if source["is_active"]
        ]
        source_summary = "\n".join(
            f"{source['id']}: {source['title']}"
            for source in active_sources[:12]
        )
        source_value = simpledialog.askstring(
            "Yeni sürümün kaynağı",
            (
                "Bu değişikliği doğrulayan source ID'yi girin. "
                "Kaynak yoksa boş bırakın.\n\n"
                f"{source_summary or 'Aktif kaynak bulunmuyor.'}"
            ),
            initialvalue="",
            parent=self,
        )
        if source_value is None:
            return
        try:
            source_id = (
                int(source_value.strip()) if source_value.strip() else None
            )
            if source_id is not None and source_id <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Geçersiz kaynak",
                "Source ID pozitif bir tam sayı olmalıdır.",
                parent=self,
            )
            return

        if not messagebox.askyesno(
            "Yeni sürümü oluştur",
            (
                f"Eski değer: {fact['value']}\n"
                f"Yeni değer: {new_value}\n"
                f"Yeni başlangıç: {valid_from}\n\n"
                "Eski kayıt silinmeyecek; tarihsel sürüm olarak korunacak."
            ),
            parent=self,
        ):
            return

        self._perform(
            lambda: supersede_fact(
                fact_id,
                new_value,
                valid_from=valid_from,
                previous_valid_to=optional_text(previous_valid_to),
                visibility=visibility,
                confidence=float(confidence),
                source_id=source_id,
            ),
            "Bilgi düzenlendi; eski sürüm tarihçede korundu.",
        )

    def show_selected_fact_corrections(self) -> None:
        try:
            fact_id = self._selected_id(self.facts_tree)
        except ValueError as error:
            messagebox.showerror("Seçim gerekli", str(error), parent=self)
            return
        self.show_fact_corrections(fact_id)

    def show_fact_corrections(self, fact_id: int) -> None:
        try:
            corrections = get_fact_corrections(fact_id)
        except Exception as error:
            messagebox.showerror(
                "Düzeltme geçmişi alınamadı",
                str(error),
                parent=self,
            )
            return
        window = tk.Toplevel(self)
        window.title(f"Fact #{fact_id} düzeltme geçmişi")
        window.geometry("760x460")
        output = tk.Text(window, wrap="word", font=("Consolas", 9))
        output.pack(fill="both", expand=True, padx=10, pady=10)
        self._set_output(
            output,
            corrections if corrections else "Bu fact için düzeltme kaydı yok.",
        )
        ttk.Button(window, text="Kapat", command=window.destroy).pack(
            pady=(0, 10)
        )

    def delete_selected_fact(self) -> None:
        try:
            fact_id = self._selected_id(self.facts_tree)
            fact = get_fact(fact_id)
        except Exception as error:
            messagebox.showerror("Silme yapılamadı", str(error), parent=self)
            return
        if not messagebox.askyesno(
            "Bilgiyi mantıksal olarak sil",
            (
                f"{fact['category']}.{fact['key']}: {fact['value']}\n\n"
                "Kayıt export ve normal sorgulardan çıkarılacak. Audit için "
                "veritabanında deleted durumunda korunacak."
            ),
            parent=self,
        ):
            return
        self._perform(
            lambda: soft_delete_fact(fact_id),
            "Bilgi mantıksal olarak silindi; audit kaydı korundu.",
        )

    def choose_document(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Belge seç",
            filetypes=(
                (
                    "Desteklenen belgeler",
                    "*.pdf *.docx *.txt *.md *.json *.csv *.html *.htm *.png *.jpg *.jpeg",
                ),
                ("Tüm dosyalar", "*.*"),
            ),
        )
        if path:
            self.d_path.set(path)

    def add_document(self) -> None:
        result = self._perform(
            lambda: ingest_document(
                self.d_type.get(),
                self.d_title.get(),
                self.d_path.get(),
                source_date=optional_text(self.d_date.get()),
            ),
            "Belge raw alana kopyalandı ve kaynak olarak kaydedildi.",
        )
        if result is not None:
            self._set_output(self.document_output, result)

    def add_manual_source(self) -> None:
        result = self._perform(
            lambda: add_source(
                "manual",
                self.manual_source_title.get(),
                source_date=optional_text(self.manual_source_date.get()),
            ),
            "Dosyasız manuel kaynak oluşturuldu.",
        )
        if result is not None:
            self.manual_source_title.set("")

    def extract_selected(self) -> None:
        result = self._perform(
            lambda: extract_source(self._selected_id(self.sources_tree)),
            "Metin çıkarıldı; candidate üretmeden önce önizleyin.",
            refresh=False,
        )
        if result is not None:
            preview = dict(result)
            text = preview.get("text", "")
            if len(text) > 6000:
                preview["text"] = text[:6000] + "\n\n[Önizleme kısaltıldı]"
            self._set_output(self.document_output, preview)

    def deactivate_selected(self) -> None:
        try:
            source_id = self._selected_id(self.sources_tree)
        except ValueError as error:
            messagebox.showerror("Seçim gerekli", str(error), parent=self)
            return
        if messagebox.askyesno(
            "Kaynağı pasifleştir",
            "Kaynak silinmeden pasifleştirilsin mi?",
            parent=self,
        ):
            self._perform(
                lambda: deactivate_source(source_id),
                "Kaynak pasifleştirildi.",
            )

    def choose_bundle(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Candidate bundle seç",
            filetypes=(("JSON", "*.json"), ("Tüm dosyalar", "*.*")),
        )
        if path:
            self.bundle_path.set(path)

    def import_bundle(self) -> None:
        result = self._perform(
            lambda: import_candidate_bundle(self.bundle_path.get()),
            "Candidate bundle staging alanına import edildi.",
        )
        if result is not None:
            self._set_output(self.document_output, result)

    def show_candidate(self, _event=None) -> None:
        try:
            candidate_id = self._selected_id(self.candidates_tree)
        except ValueError:
            return
        candidate = self.candidates.get(candidate_id)
        if candidate is not None:
            self._set_output(self.candidate_output, candidate)

    def validate_selected(self) -> None:
        result = self._perform(
            lambda: validate_candidate(self._selected_id(self.candidates_tree)),
            "Candidate validasyonu tamamlandı.",
        )
        if result is not None:
            self._set_output(self.candidate_output, result)

    def approve_selected(self) -> None:
        try:
            candidate_id = self._selected_id(self.candidates_tree)
        except ValueError as error:
            messagebox.showerror("Seçim gerekli", str(error), parent=self)
            return
        if not messagebox.askyesno(
            "Candidate onayı",
            "Bu candidate core veritabanına eklensin mi?",
            parent=self,
        ):
            return
        result = self._perform(
            lambda: approve_candidate(
                candidate_id,
                review_note=optional_text(self.review_note.get()),
            ),
            "Candidate onaylandı ve core veritabanına eklendi.",
        )
        if result is not None:
            self._set_output(self.candidate_output, result)

    def reject_selected(self) -> None:
        try:
            candidate_id = self._selected_id(self.candidates_tree)
            note = self.review_note.get().strip()
            if not note:
                raise ValueError("Reddetmek için inceleme notu zorunludur.")
        except ValueError as error:
            messagebox.showerror("Eksik bilgi", str(error), parent=self)
            return
        if messagebox.askyesno(
            "Candidate reddi",
            "Candidate audit kaydı korunarak reddedilsin mi?",
            parent=self,
        ):
            self._perform(
                lambda: reject_candidate(candidate_id, note),
                "Candidate reddedildi; audit kaydı korundu.",
            )

    def export(self) -> None:
        result = self._perform(
            export_all_datasets,
            "Dataset exportları üretildi.",
            refresh=False,
        )
        if result is not None:
            self._set_output(self.export_output, result)


def main() -> None:
    initialize_core_database()
    initialize_staging_database()
    PersonalDatasetApp().mainloop()


if __name__ == "__main__":
    main()
