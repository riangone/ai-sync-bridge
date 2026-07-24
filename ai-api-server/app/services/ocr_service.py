"""
OCR Service (Scoped)
本番用途では pytesseract / cloud OCR に差し替える。demo_mode ではファイル名/サイズから
擬似的な抽出結果を返し、拡張機能側のUIフロー検証を可能にする。
"""
import re


class OcrService:
    def __init__(self, demo_mode: bool = True):
        self.demo_mode = demo_mode

    def extract(self, filename: str, content: bytes) -> dict:
        if self.demo_mode:
            return self._mock_extract(filename, content)
        raise NotImplementedError("実OCRエンジン(pytesseract等)を接続してください")

    def _mock_extract(self, filename: str, content: bytes) -> dict:
        size_kb = max(1, len(content) // 1024)
        text = (
            f"請求書番号: INV-{size_kb:04d}\n"
            f"発行日: 2026-07-23\n"
            f"金額: ¥{size_kb * 1234}\n"
            f"取引先: サンプル株式会社"
        )
        fields = {}
        for line in text.splitlines():
            if ":" in line or "：" in line:
                key, _, val = re.split("[:：]", line, maxsplit=1)
                fields[key.strip()] = val.strip()
        return {
            "filename": filename,
            "extracted_text": text,
            "fields": fields,
            "confidence": 0.87,
        }
