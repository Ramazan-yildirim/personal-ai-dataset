import unittest
from unittest.mock import patch


from src.exporters.datasets import export_all_datasets


class ExportAllDatasetsTestCase(unittest.TestCase):
    @patch("src.exporters.datasets.export_rag")
    @patch("src.exporters.datasets.export_finetuning")
    @patch("src.exporters.datasets.export_transformer")
    def test_uses_all_default_exporters(
        self,
        transformer,
        finetuning,
        rag,
    ):
        transformer.return_value = {"format": "transformer"}
        finetuning.return_value = {"format": "finetuning"}
        rag.return_value = {"format": "rag"}

        result = export_all_datasets()

        transformer.assert_called_once_with()
        finetuning.assert_called_once_with()
        rag.assert_called_once_with()
        self.assertEqual(
            result,
            {
                "transformer": {"format": "transformer"},
                "finetuning": {"format": "finetuning"},
                "rag": {"format": "rag"},
            },
        )


if __name__ == "__main__":
    unittest.main()
