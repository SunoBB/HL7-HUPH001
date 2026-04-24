# `translate_vi_med_to_en.py`

Script Python dịch tiếng Việt sang tiếng Anh y khoa thông qua backend HTTP.

## Mục đích

Script này không gọi model trực tiếp. Nó gửi request JSON tới backend của bạn và đọc kết quả dịch từ response JSON.

## Cách chạy

```bash
cd /home/suno/Downloads/HL7
python3 scripts/translate_vi_med_to_en.py --text "Bệnh nhân đau ngực, khó thở và sốt 38.5 độ C."
```

Hoặc đọc từ file:

```bash
python3 scripts/translate_vi_med_to_en.py --file note_vi.txt
```

Hoặc pipe:

```bash
echo "Bệnh nhân có tiền sử tăng huyết áp và đái tháo đường type 2." | python3 scripts/translate_vi_med_to_en.py
```

## Biến môi trường

- `TRANSLATE_BACKEND_URL`: URL backend dịch
- `TRANSLATE_INPUT_FIELD`: field backend nhận text, mặc định `text`
- `TRANSLATE_OUTPUT_FIELD`: field backend trả bản dịch, mặc định `translation`
- `TRANSLATE_SOURCE_LANG`: mặc định `vi`
- `TRANSLATE_TARGET_LANG`: mặc định `en-med`
- `TRANSLATE_TIMEOUT`: timeout request, mặc định `60`
- `TRANSLATE_AUTH_HEADER`: tên header auth, ví dụ `Authorization`
- `TRANSLATE_AUTH_TOKEN`: giá trị auth, ví dụ `Bearer ...`

Ví dụ:

```bash
TRANSLATE_BACKEND_URL=http://localhost:9000/api/translate \
TRANSLATE_AUTH_HEADER=Authorization \
TRANSLATE_AUTH_TOKEN="Bearer my-token" \
python3 scripts/translate_vi_med_to_en.py --text "Bệnh nhân ho khạc đờm vàng 3 ngày."
```

## Request JSON mặc định

```json
{
  "text": "Bệnh nhân đau ngực",
  "source_language": "vi",
  "target_language": "en-med",
  "domain": "medical",
  "instruction": "Translate Vietnamese clinical text into precise medical English. Preserve meaning, medications, diagnoses, abbreviations, units, and chronology."
}
```

## Response JSON được hỗ trợ

Script ưu tiên đọc field:

1. `translation`
2. `translated_text`
3. `output`
4. `result`
5. `message`
6. `data.translation`
