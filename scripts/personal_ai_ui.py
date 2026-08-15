"""Single-window local UI for the personal dataset pipeline."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))


from src.database.migrations import initialize_core_database
from src.database.persons import create_person, list_persons
from src.database.sources import add_source, deactivate_source, list_sources
from src.database.staging_connection import initialize_staging_database
from src.exporters.common import EXPORT_ROOT, load_export_facts
from src.exporters.finetuning import export_finetuning
from src.exporters.rag import export_rag
from src.exporters.transformer import export_transformer
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


def selected_visibilities(
    include_private: bool,
    include_internal: bool,
) -> tuple[str, ...]:
    values = ["public"]
    if include_private:
        values.append("private")
    if include_internal:
        values.append("internal")
    return tuple(values)


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


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
        self.facts_tree = self._tree(
            self.people_tab,
            (
                ("id", "ID", 50),
                ("category", "Kategori", 110),
                ("key", "Anahtar", 140),
                ("value", "Değer", 310),
                ("visibility", "Görünürlük", 90),
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
        form = ttk.LabelFrame(self.export_tab, text="Ayarlar", padding=10)
        form.pack(fill="x")
        self.e_private = tk.BooleanVar(value=False)
        self.e_internal = tk.BooleanVar(value=False)
        self.e_output = tk.StringVar()
        self.e_supplemental = tk.StringVar()
        self.e_max = tk.StringVar(value="800")
        self.e_overlap = tk.StringVar(value="100")
        ttk.Checkbutton(
            form, text="private dahil", variable=self.e_private
        ).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            form, text="internal dahil", variable=self.e_internal
        ).grid(row=0, column=1, sticky="w")
        ttk.Label(form, text="public her zaman dahil").grid(
            row=0, column=2, sticky="w"
        )
        ttk.Label(form, text="Output klasörü (opsiyonel)").grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Entry(form, textvariable=self.e_output).grid(
            row=2, column=0, columnspan=2, sticky="ew", padx=(0, 5)
        )
        ttk.Button(form, text="Seç", command=self.choose_export_dir).grid(
            row=2, column=2, sticky="w"
        )
        ttk.Label(form, text="Supplemental klasörü").grid(
            row=3, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Entry(form, textvariable=self.e_supplemental).grid(
            row=4, column=0, columnspan=2, sticky="ew", padx=(0, 5)
        )
        ttk.Button(form, text="Seç", command=self.choose_supplemental).grid(
            row=4, column=2, sticky="w"
        )
        ttk.Label(form, text="RAG max / overlap").grid(
            row=5, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Entry(form, textvariable=self.e_max, width=10).grid(
            row=6, column=0, sticky="w"
        )
        ttk.Entry(form, textvariable=self.e_overlap, width=10).grid(
            row=6, column=1, sticky="w"
        )
        form.columnconfigure(0, weight=1)
        form.columnconfigure(1, weight=1)
        buttons = ttk.Frame(self.export_tab)
        buttons.pack(fill="x", pady=8)
        for name, title in (
            ("transformer", "Transformer"),
            ("finetuning", "Fine-tuning"),
            ("rag", "RAG"),
            ("all", "Tümünü üret"),
        ):
            ttk.Button(
                buttons,
                text=title,
                command=lambda value=name: self.export(value),
            ).pack(side="left", padx=(0, 5))
        ttk.Label(
            self.export_tab,
            text="Private/internal veriler yalnızca açıkça seçilirse export edilir.",
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
            facts = load_export_facts(visibilities=VISIBILITIES)
        except Exception as error:
            self.status_var.set(f"Fact yenileme hatası: {error}")
            return
        for fact in facts:
            if fact["person_id"] == person_id:
                self.facts_tree.insert(
                    "",
                    "end",
                    values=(
                        fact["id"],
                        fact["category"],
                        fact["key"],
                        fact["value"],
                        fact["visibility"],
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

    def choose_export_dir(self) -> None:
        path = filedialog.askdirectory(parent=self, title="Export klasörü")
        if path:
            self.e_output.set(path)

    def choose_supplemental(self) -> None:
        path = filedialog.askdirectory(parent=self, title="Supplemental klasörü")
        if path:
            self.e_supplemental.set(path)

    def export(self, target_name: str) -> None:
        def action():
            visibilities = selected_visibilities(
                self.e_private.get(),
                self.e_internal.get(),
            )
            custom_root = optional_text(self.e_output.get())
            output_root = (
                Path(custom_root).resolve()
                if custom_root is not None
                else EXPORT_ROOT
            )
            result = {}
            if target_name in {"transformer", "all"}:
                result["transformer"] = export_transformer(
                    output_dir=output_root / "transformer",
                    supplemental_dir=optional_text(self.e_supplemental.get()),
                    visibilities=visibilities,
                )
            if target_name in {"finetuning", "all"}:
                result["finetuning"] = export_finetuning(
                    output_dir=output_root / "finetuning",
                    visibilities=visibilities,
                )
            if target_name in {"rag", "all"}:
                result["rag"] = export_rag(
                    output_dir=output_root / "rag",
                    visibilities=visibilities,
                    max_chars=int(self.e_max.get()),
                    overlap_chars=int(self.e_overlap.get()),
                )
            return result

        result = self._perform(
            action,
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
