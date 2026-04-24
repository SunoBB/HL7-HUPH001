# Luồng Code MCP Hiện Tại

## 1. Điểm vào của chương trình

File entrypoint là [fhir-mcp-server/src/fhir_mcp_server/__main__.py](/home/suno/Downloads/HL7/fhir-mcp-server/src/fhir_mcp_server/__main__.py:1). File này chỉ gọi `main()` trong [fhir-mcp-server/src/fhir_mcp_server/server.py](/home/suno/Downloads/HL7/fhir-mcp-server/src/fhir_mcp_server/server.py:699).

Trong `main()` hệ thống làm 3 việc chính:

1. Tạo instance `FastMCP`.
2. Đăng ký các tool MCP.
3. Đăng ký route OAuth callback rồi chạy `mcp.run(...)`.

## 2. Cấu hình được nạp như thế nào

Config được đọc qua class `ServerConfigs` trong [fhir-mcp-server/src/fhir_mcp_server/oauth/types.py](/home/suno/Downloads/HL7/fhir-mcp-server/src/fhir_mcp_server/oauth/types.py:28).

Những biến quan trọng:

- `FHIR_MCP_HOST`, `FHIR_MCP_PORT`, `FHIR_MCP_SERVER_URL`: địa chỉ MCP server.
- `FHIR_SERVER_BASE_URL`: địa chỉ FHIR server backend.
- `FHIR_SERVER_CLIENT_ID`, `FHIR_SERVER_CLIENT_SECRET`: thông tin OAuth client để nối với FHIR auth server.
- `FHIR_SERVER_SCOPES`: scope cần xin.
- `FHIR_SERVER_ACCESS_TOKEN`: token cố định, nếu muốn bỏ qua luồng lấy token động.
- `FHIR_SERVER_DISABLE_AUTHORIZATION`: bật hoặc tắt auth của MCP server.

Từ đây, code sinh ra:

- `discovery_url`: `.../.well-known/smart-configuration`
- `metadata_url`: `.../metadata?_format=json`
- `effective_server_url`: URL public của MCP server dùng cho callback OAuth.

## 3. Lúc server khởi động

Hàm `configure_mcp_server()` ở [fhir-mcp-server/src/fhir_mcp_server/server.py](/home/suno/Downloads/HL7/fhir-mcp-server/src/fhir_mcp_server/server.py:110) tạo `FastMCP`.

Mặc định server chạy với:

- `json_response=True`
- `stateless_http=True`
- host và port lấy từ config

Nếu `FHIR_SERVER_DISABLE_AUTHORIZATION=false`:

- MCP auth được bật.
- `OAuthServerProvider` được gắn vào `auth_server_provider`.
- `AuthSettings` được tạo với issuer là chính MCP server.
- Client MCP có thể đăng ký và đi qua luồng OAuth.

Nếu `FHIR_SERVER_DISABLE_AUTHORIZATION=true`:

- MCP server không bật auth.
- Tool có thể được gọi trực tiếp.
- Nếu backend FHIR vẫn cần token thì phải cấp `FHIR_SERVER_ACCESS_TOKEN` hoặc có cơ chế token khác.

## 4. Luồng auth OAuth hiện tại

Class xử lý auth là `OAuthServerProvider` trong [fhir-mcp-server/src/fhir_mcp_server/oauth/server_provider.py](/home/suno/Downloads/HL7/fhir-mcp-server/src/fhir_mcp_server/oauth/server_provider.py:50).

### 4.1 Client MCP bắt đầu đăng nhập

Khi MCP client muốn auth, `authorize()` sẽ:

1. Gọi SMART discovery qua `/.well-known/smart-configuration`.
2. Lấy `authorization_endpoint` và `token_endpoint`.
3. Tạo `code_verifier` và `code_challenge` theo PKCE.
4. Tạo `state`.
5. Lưu thông tin tạm vào `state_mapping`:
   - `redirect_uri`
   - `code_verifier`
   - `code_challenge`
   - `client_id`
   - `scope`
6. Tạo URL auth trỏ sang FHIR authorization server.

Nội dung này nằm ở [fhir-mcp-server/src/fhir_mcp_server/oauth/server_provider.py](/home/suno/Downloads/HL7/fhir-mcp-server/src/fhir_mcp_server/oauth/server_provider.py:75).

### 4.2 FHIR auth server callback về MCP

Server đăng ký route `/oauth/callback` trong [fhir-mcp-server/src/fhir_mcp_server/server.py](/home/suno/Downloads/HL7/fhir-mcp-server/src/fhir_mcp_server/server.py:142).

Khi FHIR auth server redirect về:

1. MCP server nhận `code` và `state`.
2. Gọi `handle_mcp_oauth_callback(code, state)`.
3. Hàm này đọc thông tin trước đó từ `state_mapping`.
4. Tạo một `mcp_auth_code` nội bộ.
5. Lưu mapping từ `mcp_auth_code` sang authorization code thật của FHIR server.
6. Redirect ngược lại cho MCP client bằng `construct_redirect_uri(...)`.

Ý nghĩa:

- MCP client không cầm trực tiếp authorization code gốc của FHIR.
- MCP server dùng một mã nội bộ để quản lý bước exchange tiếp theo.

### 4.3 Đổi authorization code lấy token

Khi MCP framework yêu cầu đổi code lấy token, `exchange_authorization_code()` sẽ:

1. Lấy authorization code đã lưu.
2. Gọi token endpoint thật của FHIR server bằng `perform_token_flow(...)`.
3. Nhận về access token và refresh token thật của FHIR.
4. Tạo ra `mcp_access_token` và `mcp_refresh_token` mới.
5. Lưu mapping:
   - MCP token -> FHIR token thật
   - FHIR access token -> metadata token, để sau này đọc `id_token`
6. Trả về token dạng MCP cho client.

Code nằm ở [fhir-mcp-server/src/fhir_mcp_server/oauth/server_provider.py](/home/suno/Downloads/HL7/fhir-mcp-server/src/fhir_mcp_server/oauth/server_provider.py:166).

### 4.4 Refresh token

Khi refresh, `exchange_refresh_token()` lặp lại ý tưởng trên:

1. Gọi token endpoint thật của FHIR server với grant `refresh_token`.
2. Nhận token mới.
3. Tạo cặp MCP token mới.
4. Cập nhật lại mapping trong memory.

## 5. Token được lấy ra để gọi FHIR server như thế nào

Mỗi tool không tự tạo token. Tất cả đi qua `get_user_access_token()` và `get_async_fhir_client()` trong [fhir-mcp-server/src/fhir_mcp_server/server.py](/home/suno/Downloads/HL7/fhir-mcp-server/src/fhir_mcp_server/server.py:58).

Trình tự:

1. Nếu `FHIR_SERVER_ACCESS_TOKEN` được set:
   - Dùng token cố định này.
   - Không cần lấy token từ auth context.
2. Nếu không có token cố định:
   - Gọi `get_access_token()` của MCP auth middleware.
   - Đây là MCP token đã được map sang token FHIR thật.
3. Tạo `AsyncFHIRClient` bằng `create_async_fhir_client()`.
4. Gắn header:
   - `Accept: application/fhir+json`
   - `Content-Type: application/fhir+json`
   - `Authorization: Bearer <fhir-access-token>` nếu có token

Code tạo FHIR client nằm ở [fhir-mcp-server/src/fhir_mcp_server/utils.py](/home/suno/Downloads/HL7/fhir-mcp-server/src/fhir_mcp_server/utils.py:16).

## 6. Luồng gọi tool MCP

Tất cả tool được đăng ký trong `register_mcp_tools()` ở [fhir-mcp-server/src/fhir_mcp_server/server.py](/home/suno/Downloads/HL7/fhir-mcp-server/src/fhir_mcp_server/server.py:173).

### 6.1 `get_capabilities`

Tool này:

1. Gọi `metadata_url` của FHIR server.
2. Lấy `CapabilityStatement`.
3. Tìm resource type được yêu cầu.
4. Rút gọn thông tin về:
   - `searchParam`
   - `operation`
   - `interaction`
   - `searchInclude`
   - `searchRevInclude`

Nó không dùng `fhirpy`, mà gọi HTTP trực tiếp qua `get_capability_statement()` trong [fhir-mcp-server/src/fhir_mcp_server/utils.py](/home/suno/Downloads/HL7/fhir-mcp-server/src/fhir_mcp_server/utils.py:83).

### 6.2 `search`

Tool `search`:

1. Kiểm tra `type`.
2. Tạo `AsyncFHIRClient`.
3. Gọi `client.resources(type).search(Raw(**searchParam)).fetch_raw()`.
4. Trả về danh sách resource raw từ FHIR server.

Nếu FHIR backend trả `OperationOutcome`, code sẽ bắt exception và trả lại lỗi đã chuẩn hóa.

### 6.3 `read`

Tool `read`:

1. Kiểm tra `type`.
2. Tạo client.
3. Gọi `client.resource(resource_type=type, id=id).execute(...)`.
4. Có thể kèm:
   - `searchParam`
   - `operation`
5. Nếu kết quả là Bundle thì `get_bundle_entries()` sẽ bóc `entry[].resource`.

### 6.4 `create`

Tool `create`:

1. Kiểm tra `type`.
2. Tạo client.
3. Gọi `execute(...)` với `data=payload`.
4. Trả resource vừa tạo hoặc `OperationOutcome`.

### 6.5 `update`

Tool `update`:

1. Kiểm tra `type`.
2. Tạo client.
3. Gọi `PUT`.
4. Payload được merge thêm `id`.
5. Trả resource đã cập nhật.

### 6.6 `delete`

Tool `delete`:

1. Kiểm tra `type`.
2. Bắt buộc phải có `id` hoặc `searchParam`.
3. Gọi `DELETE`.
4. Nếu backend trả body thì trả body đó.
5. Nếu không có body thì tự tạo `OperationOutcome` thông báo xóa thành công.

### 6.7 `get_user`

Tool `get_user` đặc biệt hơn:

1. Lấy token hiện tại.
2. Tìm metadata của token trong `server_provider.token_metadata_mapping`.
3. Đọc `id_token`.
4. Parse claim `fhirUser`.
5. Tách `resource_type` và `resource_id`.
6. Gọi FHIR server để lấy resource của user.
7. Rút gọn profile bằng `build_user_profile()`.

Phần parse `fhirUser` nằm ở [fhir-mcp-server/src/fhir_mcp_server/oauth/types.py](/home/suno/Downloads/HL7/fhir-mcp-server/src/fhir_mcp_server/oauth/types.py:159).

## 7. Xử lý lỗi

Code hiện tại xử lý lỗi theo mẫu chung:

- Thiếu tham số bắt buộc: trả `OperationOutcome` với code `required`.
- Không có quyền hoặc chưa auth: trả `OperationOutcome` với code `forbidden`.
- Không tìm thấy resource: trả `not-found`.
- Lỗi bất ngờ: trả `exception`.
- Nếu FHIR backend đã ném `OperationOutcome`, code cố gắng trả lại `issue` từ backend.

Hàm hỗ trợ nằm ở [fhir-mcp-server/src/fhir_mcp_server/utils.py](/home/suno/Downloads/HL7/fhir-mcp-server/src/fhir_mcp_server/utils.py:55).

## 8. Một số điểm kiến trúc quan trọng

### 8.1 Tất cả session auth đang ở trong memory

Những mapping sau đều nằm trong RAM của process:

- `clients`
- `auth_code_mapping`
- `token_mapping`
- `state_mapping`
- `token_metadata_mapping`

Nếu restart server:

- mất session
- mất token mapping
- client có thể phải đăng nhập lại

### 8.2 MCP token và FHIR token là 2 lớp khác nhau

MCP client thấy token của MCP.

Server nội bộ map MCP token đó sang FHIR token thật để gọi backend. Đây là ý chính của `OAuthServerProvider`.

### 8.3 `get_user` phụ thuộc vào `id_token`

Nếu auth server không trả `id_token`, hoặc `id_token` không có claim `fhirUser`, thì `get_user` gần như không lấy được profile.

### 8.4 `get_capabilities` được khuyến nghị gọi trước

Mô tả tool ghi rõ model hoặc client nên gọi `get_capabilities` trước khi dùng `search`, `read`, `create`, `update`, `delete`, để biết resource đó hỗ trợ tham số nào.

## 9. Tóm tắt luồng end-to-end

Có thể hiểu đơn giản như sau:

1. MCP client kết nối vào FHIR MCP Server.
2. Nếu auth bật:
   - client đi qua OAuth hoặc SMART flow
   - MCP server đổi code và token với FHIR auth server
   - MCP server giữ mapping MCP token <-> FHIR token
3. Client gọi một tool MCP.
4. Tool lấy access token hiện tại.
5. Tool tạo `AsyncFHIRClient`.
6. Tool gọi FHIR server thật.
7. MCP server trả kết quả JSON hoặc `OperationOutcome` về cho client.

## 10. Sơ đồ ngắn

```text
MCP Client
   |
   v
FHIR MCP Server (FastMCP)
   |-- OAuthServerProvider
   |     |-- SMART discovery
   |     |-- authorize
   |     |-- token exchange
   |     `-- token mapping in memory
   |
   |-- MCP Tools
   |     |-- get_capabilities
   |     |-- search
   |     |-- read
   |     |-- create
   |     |-- update
   |     |-- delete
   |     `-- get_user
   |
   `-- AsyncFHIRClient / fhirpy
          |
          v
      FHIR Server Backend
```
