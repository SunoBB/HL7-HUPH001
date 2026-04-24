# HL7 FHIR Setup Guide on Ubuntu

This document is for running HAPI FHIR on Ubuntu, not Windows. It covers:

- local prerequisites on Ubuntu
- running HAPI FHIR with Docker Compose
- basic verification commands
- the startup issue found on this machine during testing

## Project Files

This folder already contains:

- `docker-compose.yml`
- `hapi.application.yaml`

Run Docker commands from this directory:

```bash
cd /home/suno/Downloads/HL7/HL7_FHIR
```

That matters because `docker-compose.yml` mounts `./hapi.application.yaml` into the HAPI container.

## What To Open On Ubuntu

- `Terminal`
- `VS Code`
- a browser

Optional:

- `Files` if you prefer browsing folders graphically
- Docker Desktop UI if you want to inspect containers visually

## Prerequisites

Install basic tools:

```bash
sudo apt update
sudo apt install -y curl git unzip wget
```

Check Docker:

```bash
docker --version
docker compose version
```

Check Java and Maven if you also want to run HAPI locally outside Docker:

```bash
java -version
mvn -version
```

On this Ubuntu machine, the recorded versions were:

```text
OpenJDK 21.0.10
Apache Maven 3.6.3
Docker 29.3.0
Docker Compose v2.27.0-desktop.2
```

## Docker Configuration In This Project

The current Docker setup uses:

- HAPI image: `hapiproject/hapi:latest`
- PostgreSQL image: `postgres:16-alpine`
- host port `8081` mapped to container port `8080`
- PostgreSQL host port `5432`

FHIR base URL from the current config:

```text
http://localhost:8081/fhir
```

Main config file:

- [`hapi.application.yaml`](/home/suno/Downloads/HL7/HL7_FHIR/hapi.application.yaml)

Current settings in that file:

- PostgreSQL datasource at `hapi-fhir-postgres:5432/hapi`
- username `admin`
- password `admin`
- `auto_create_placeholder_reference_targets: true`
- `enforce_referential_integrity_on_write: false`
- `server_address: http://localhost:8081/fhir`

## Run With Docker

Start the stack:

```bash
cd /home/suno/Downloads/HL7/HL7_FHIR
docker compose up -d
```

Check status:

```bash
docker compose ps
```

Read logs:

```bash
docker compose logs --tail=200
docker compose logs -f hapi-fhir-jpaserver-start
```

Stop the stack:

```bash
docker compose down
```

Stop and remove the database volume too:

```bash
docker compose down -v
```

Use `down -v` only when you want to reset PostgreSQL data.

## Verify HAPI FHIR

After startup, check the root page:

```bash
curl -I http://localhost:8081/
```

Check CapabilityStatement:

```bash
curl http://localhost:8081/fhir/metadata
```

Pretty-print JSON if `jq` is installed:

```bash
curl -s http://localhost:8081/fhir/metadata | jq '.resourceType'
```

Expected value:

```text
"CapabilityStatement"
```

Open in browser:

- `http://localhost:8081/`
- `http://localhost:8081/fhir/metadata`

## What Was Tested On This Machine

Test date:

```text
2026-03-26
```

What I verified:

- Docker is installed
- Docker Compose is installed
- the PostgreSQL container `hapi-fhir-postgres` is running and healthy
- an older HAPI container named `hapi-fhir-jpaserver-start` already exists on this machine

What failed:

- `docker compose up -d` could not create a new HAPI container because the old container name already exists
- starting the old HAPI container also failed because it points to the wrong mounted config path

Observed Docker error:

```text
error mounting "/host_mnt/home/suno/Downloads/HL7/hapi.application.yaml" to "/app/config/application.yaml"
```

This indicates the old container was created with the wrong host path. The correct config file for this project is:

```text
/home/suno/Downloads/HL7/HL7_FHIR/hapi.application.yaml
```

## Fix The Existing Docker Issue

If you want to reuse this project cleanly, remove the stale HAPI container and recreate it from this folder:

```bash
cd /home/suno/Downloads/HL7/HL7_FHIR
docker rm -f hapi-fhir-jpaserver-start
docker compose up -d
```

Then verify:

```bash
docker compose ps
curl http://localhost:8081/fhir/metadata
```

If the database was initialized badly and you want a clean restart:

```bash
cd /home/suno/Downloads/HL7/HL7_FHIR
docker compose down -v
docker rm -f hapi-fhir-jpaserver-start 2>/dev/null || true
docker compose up -d
```

## Local Run Without Docker

If you later want to run HAPI locally with Java and Maven instead of Docker:

1. install Java 21
2. install Maven
3. clone `hapi-fhir-jpaserver-starter`
4. configure `application.yaml`
5. run Maven

Example commands:

```bash
java -version
mvn -version
git clone https://github.com/hapifhir/hapi-fhir-jpaserver-starter.git
cd hapi-fhir-jpaserver-starter
mvn spring-boot:run
```

For Tomcat deployment:

```bash
mvn clean install
```

Then deploy the generated WAR into Tomcat `webapps/`.

## VS Code

Open this folder in VS Code:

```bash
code /home/suno/Downloads/HL7/HL7_FHIR
```

Useful files:

- [`docker-compose.yml`](/home/suno/Downloads/HL7/HL7_FHIR/docker-compose.yml)
- [`hapi.application.yaml`](/home/suno/Downloads/HL7/HL7_FHIR/hapi.application.yaml)

## Gemini And MCP

Workspace này đã có sẵn cấu hình MCP local cho Gemini và VS Code để gọi FHIR server tại `http://localhost:8081/fhir`.

Các file chính:

- [`.gemini/settings.json`](/home/suno/Downloads/HL7/.gemini/settings.json)
- [`.vscode/mcp.json`](/home/suno/Downloads/HL7/.vscode/mcp.json)
- [`MCP_GEMINI_VSCODE.md`](/home/suno/Downloads/HL7/MCP_GEMINI_VSCODE.md)
- [`scripts/gemini_hl7.sh`](/home/suno/Downloads/HL7/scripts/gemini_hl7.sh)

Chạy Gemini trong workspace này:

```bash
cd /home/suno/Downloads/HL7
bash scripts/gemini_hl7.sh
```

Tài liệu `MCP_GEMINI_VSCODE.md` có:

- cấu hình đầy đủ cho Gemini và VS Code
- tuỳ chọn `stdio` và `streamable-http`
- prompt mẫu cho truy vấn tổng hợp
- prompt mẫu cho báo cáo Markdown
- prompt mẫu để sinh biểu đồ Mermaid trực quan
- [`readme.md`](/home/suno/Downloads/HL7/HL7_FHIR/readme.md)

## Troubleshooting

If `docker compose up -d` says a container name already exists:

```bash
docker rm -f hapi-fhir-jpaserver-start
```

If HAPI starts but `http://localhost:8081/metadata` fails, use the correct FHIR path:

```text
http://localhost:8081/fhir/metadata
```

If PostgreSQL is unhealthy:

```bash
docker compose logs hapi-fhir-postgres
```

If HAPI is unhealthy or exits:

```bash
docker compose logs hapi-fhir-jpaserver-start
```

If you want to fully reset the stack:

```bash
docker compose down -v
docker rm -f hapi-fhir-jpaserver-start
docker compose up -d
```

## Quick Start

Most common flow:

```bash
cd /home/suno/Downloads/HL7/HL7_FHIR
docker compose up -d
docker compose ps
curl http://localhost:8081/fhir/metadata
```


## References
https://github.com/IHTSDO/snowstorm/tree/master/docs



Dùng Postman được. Bạn có thể CRUD qua MCP endpoint http://127.0.0.1:8000/mcp/.

Chuẩn bị
Chạy MCP server trước:

cd /home/suno/Downloads/HL7
FHIR_SERVER_BASE_URL=http://localhost:8081/fhir \
FHIR_SERVER_DISABLE_AUTHORIZATION=True \
PYTHONPATH=/home/suno/Downloads/HL7/fhir-mcp-server/src \
/home/suno/Downloads/HL7/venv/bin/python -m fhir_mcp_server --transport streamable-http --log-level INFO
Postman Setup
Tạo 1 collection, rồi với mọi request:

Method: POST
URL: http://127.0.0.1:8000/mcp/
Headers:
Content-Type: application/json
Accept: application/json, text/event-stream
Body: raw + JSON
1. Initialize

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2025-03-26",
    "capabilities": {},
    "clientInfo": {
      "name": "postman",
      "version": "1.0"
    }
  }
}
2. List tools

{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/list",
  "params": {}
}
3. Get capabilities của Patient

{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "get_capabilities",
    "arguments": {
      "type": "Patient"
    }
  }
}
4. Search Patient

{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "tools/call",
  "params": {
    "name": "search",
    "arguments": {
      "type": "Patient",
      "searchParam": {
        "_count": "5"
      }
    }
  }
}
5. Create Patient

{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "tools/call",
  "params": {
    "name": "create",
    "arguments": {
      "type": "Patient",
      "payload": {
        "resourceType": "Patient",
        "name": [
          {
            "family": "Nguyen",
            "given": ["Postman MCP"]
          }
        ],
        "gender": "male",
        "birthDate": "1990-01-01"
      }
    }
  }
}
6. Read Patient
Lấy id từ kết quả create hoặc search.

{
  "jsonrpc": "2.0",
  "id": 6,
  "method": "tools/call",
  "params": {
    "name": "read",
    "arguments": {
      "type": "Patient",
      "id": "PUT_PATIENT_ID_HERE"
    }
  }
}
7. Update Patient
Nhớ giữ đúng id.

{
  "jsonrpc": "2.0",
  "id": 7,
  "method": "tools/call",
  "params": {
    "name": "update",
    "arguments": {
      "type": "Patient",
      "id": "PUT_PATIENT_ID_HERE",
      "payload": {
        "resourceType": "Patient",
        "id": "PUT_PATIENT_ID_HERE",
        "name": [
          {
            "family": "Nguyen",
            "given": ["Postman MCP Updated"]
          }
        ],
        "gender": "female",
        "birthDate": "1990-01-01"
      }
    }
  }
}
8. Delete Patient

{
  "jsonrpc": "2.0",
  "id": 8,
  "method": "tools/call",
  "params": {
    "name": "delete",
    "arguments": {
      "type": "Patient",
      "id": "PUT_PATIENT_ID_HERE"
    }
  }
}
Thứ tự test nên chạy

initialize
tools/list
get_capabilities
search
create
read
update
read lại để kiểm tra
delete
Lưu ý

GET /mcp/ trên browser ra 406 là bình thường.
Trong Postman phải dùng POST tới /mcp/, không phải GET.
MCP là JSON-RPC, nên CRUD đều đi qua tools/call, không gọi thẳng REST /Patient.
Nếu muốn, tôi có thể tạo luôn cho bạn một file Postman Collection v2.1 JSON trong repo để import thẳng.
