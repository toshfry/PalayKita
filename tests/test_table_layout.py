import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TableLayoutTests(unittest.TestCase):
    def test_transaction_tables_use_compact_action_cell_wrappers(self):
        for template_name in ("transactions.html", "commercial_customer_detail.html"):
            with self.subTest(template=template_name):
                html = (ROOT / "templates" / template_name).read_text(encoding="utf-8")

                self.assertIn('class="actions-cell"', html)
                self.assertIn('class="table-actions"', html)
                self.assertNotIn('td class="actions"', html)

    def test_table_css_keeps_action_cells_as_table_cells(self):
        css = (ROOT / "static" / "css" / "app.css").read_text(encoding="utf-8")

        self.assertIn(".actions-cell", css)
        self.assertIn(".table-actions", css)
        self.assertIn("flex-wrap: nowrap;", css)
        self.assertIn("white-space: nowrap;", css)
        self.assertNotIn(".actions {\n    display: flex;", css)
        self.assertNotIn("max-width: 190px;", css)

    def test_mark_paid_forms_preserve_scroll_after_redirect(self):
        templates = (
            "transactions.html",
            "unpaid.html",
            "commercial_customer_detail.html",
        )

        for template_name in templates:
            with self.subTest(template=template_name):
                html = (ROOT / "templates" / template_name).read_text(encoding="utf-8")
                self.assertIn("data-preserve-scroll", html)

    def test_javascript_restores_preserved_scroll_position(self):
        js = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")

        self.assertIn("setupPreservedScrollForms", js)
        self.assertIn("restorePreservedScrollPosition", js)
        self.assertIn("form[data-preserve-scroll]", js)
        self.assertIn("palaykita:scroll:", js)
        self.assertIn("sessionStorage.setItem", js)
        self.assertIn("sessionStorage.removeItem", js)
        self.assertIn("window.scrollTo", js)

    def test_new_transaction_layout_has_command_bar_and_summary_before_fields(self):
        html = (ROOT / "templates" / "transaction_form.html").read_text(encoding="utf-8")

        self.assertIn('class="txn-command-bar"', html)
        self.assertIn('class="txn-save-btn"', html)
        self.assertLess(html.index('class="txn-command-bar"'), html.index('data-txn-section="local"'))

        local_section = html.split('data-txn-section="local"', 1)[1].split('data-txn-section="commercial"', 1)[0]
        self.assertLess(local_section.index('class="calc-box'), local_section.index('class="form-grid txn-form-grid"'))

        commercial_section = html.split('data-txn-section="commercial"', 1)[1]
        self.assertLess(commercial_section.index('class="calc-box'), commercial_section.index('class="form-grid txn-form-grid"'))
        self.assertIn("Gross Commercial Fee", commercial_section)
        self.assertIn("Net Amount", commercial_section)
        commercial_summary = commercial_section.split('class="form-grid txn-form-grid"', 1)[0]
        self.assertNotIn("Amount Paid", commercial_summary)

    def test_new_transaction_layout_has_local_and_commercial_theme_styles(self):
        css = (ROOT / "static" / "css" / "app.css").read_text(encoding="utf-8")
        js = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")

        self.assertIn(".txn-command-bar", css)
        self.assertIn(".txn-form-card.txn-type-local .txn-save-btn", css)
        self.assertIn(".txn-form-card.txn-type-commercial .txn-save-btn", css)
        self.assertIn("background: var(--gold);", css)
        self.assertIn("@media (max-width: 899px)", css)
        self.assertIn("@media (max-width: 480px)", css)
        self.assertIn(".txn-type-switch", css)
        self.assertIn("grid-template-columns: 1fr;", css)

        self.assertIn("txn-type-local", js)
        self.assertIn("txn-type-commercial", js)
        self.assertIn("commercialGrossPreview", js)
        self.assertIn("commercialNetPreview", js)


if __name__ == "__main__":
    unittest.main()
