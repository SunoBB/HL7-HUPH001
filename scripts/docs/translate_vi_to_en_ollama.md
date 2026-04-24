# `translate_vi_to_en_ollama.py`

Script CLI dịch tiếng Việt sang tiếng Anh trực tiếp bằng `ollama`.

Model local đã thấy trên máy:

```text
llama3.2:latest
```

## Cách chạy

```bash
cd /home/suno/Downloads/HL7
python3 scripts/translate_vi_to_en_ollama.py --text "Bệnh nhân đau ngực và khó thở"
```

Hoặc từ file:

```bash
python3 scripts/translate_vi_to_en_ollama.py --file note_vi.txt
```

Hoặc pipe:

```bash
echo "Bệnh nhân có tiền sử tăng huyết áp và đái tháo đường type 2" | \
python3 scripts/translate_vi_to_en_ollama.py
```

## Chọn model khác

```bash
python3 scripts/translate_vi_to_en_ollama.py \
  --model llama3.2:latest \
  --text "Bệnh nhân sốt cao 39 độ, ho và đau ngực"
```

## Biến môi trường

- `OLLAMA_MODEL`
- `OLLAMA_SYSTEM_PROMPT`
