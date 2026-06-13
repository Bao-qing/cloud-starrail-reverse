# miHoYo 云崩铁协议说明

本文档整理米哈游云崩铁（`hkrpg_cn`）Web 云游戏链路的逆向结果。内容来自两部分：

- 当前 Python 实现：`core/dispatcher.py`、`core/session.py`、`core/protocol.py`、`core/config.py`。
- 官方 Web SDK 参考： `cg_sdk_066992fd.js` 与 `web_01733375.js` 中的 protobuf、命令号、调度接口和 RTC 状态机。

## 1. 总览

云崩铁客户端链路分为两个大阶段：

1. **HTTP 调度阶段**
   - 使用米哈游网页登录 Cookie 同步 Web 账号态。
   - 生成 `x-rpc-combo_token`。
   - 查询状态、测速节点、队列、钱包。
   - 调用 `paasDispatch`，排队并获取 `finish_result.sdk_param`。

2. **实时会话阶段**
   - 解码 `sdk_param`，得到游戏 token、Pod、RTC WebSocket、UDP candidate、控制通道等参数。
   - 连接 `game_server_wss_url + /rtc-sdk`。
   - 通过 WebSocket 外层帧承载：
     - RTC 信令 JSON。
     - 云游戏 TCP/Proxy protobuf Packet。
     - 握手 JSON。
   - 建立 WebRTC，接收音视频和 DataChannel。
   - 通过独立游戏控制通道或 RTC DataChannel 发送输入与心跳。
   - 通过 RMQ + AES 加密 JSON 响应游戏内 SDK 回调。

核心公开门面是 `core.CloudGame`：

- `Dispatcher` 负责 HTTP 调度。
- `GameSession` 负责 WebSocket/WebRTC/控制通道。
- `Protocol` 负责 protobuf-like 编码、Packet 封包、WS 帧、RMQ、SDK AES、输入包。

## 2. 业务标识与固定端点

### 2.1 业务常量

| 名称 | 值 | 位置 |
| --- | --- | --- |
| `biz_key` | `hkrpg_cn` | 调度和 SDK 参数 |
| `x-rpc-op_biz` | `clgm_hkrpg-cn` | 调度请求头 |
| `x-rpc-client_type` | `19` | 云游戏调度 Web PC |
| `x-rpc-vendor_id` | `2` | 调度请求头 |
| `x-rpc-cps` | `keyboard_mihoyo` | 调度与 SDK 回调 |
| `x-rpc-language` | `zh-cn` | 调度请求头 |
| `WEB client_type` | `25` | 账号 Web 验证 |
| `CG_SDK_VERSION` | `6.2.0.24` | RTC SDK 协议 |
| `WEB_SDK_VERSION` | `2.50.1` | `webVerifyForGame` |
| `WEB_MDK_VERSION` | `2.49.0` | `webLogin` |
| `WEB_APP_ID` | `8` | Web login app id |
| `WEB_CHANNEL_ID` | `1` | Web login channel id |

### 2.2 HTTP 端点

| 用途 | 方法 | URL/路径 |
| --- | --- | --- |
| 云游戏 API Base | - | `https://cg-hkrpg-api.mihoyo.com/hkrpg_cn/cg` |
| Web 游戏验证 | POST | `https://passport-api.mihoyo.com/account/ma-cn-session/web/webVerifyForGame` |
| Web combo 登录 | POST | `https://hkrpg-sdk.mihoyo.com/hkrpg_cn/combo/granter/login/webLogin` |
| 钱包 | GET | `/wallet/wallet/get` |
| 状态检查 | POST | `/dispatcher/api/statusCheck` |
| ping server 列表 | POST | `/dispatcher/api/listPingServer` |
| 节点列表 | POST | `/dispatcher/api/getNodesInfo` |
| 预调度验证 | POST | `/dispatcher/api/preDispatchVerify` |
| 实例调度 | POST | `/dispatcher/api/paasDispatch` |
| 查询排队 ticket | POST | `/dispatcher/api/getDispatchTicketInfo` |
| 确认排队 ticket | POST | `/dispatcher/api/ackDispatchTicket` |

## 3. HTTP 账号与调度协议

### 3.1 Cookie 与设备 ID

客户端需要米哈游登录 Cookie。实现会优先从显式配置读取，其次读取环境变量 `CLOUD_GAME_COOKIE`。

设备 ID 读取顺序：

1. Cookie 中的 `_MHYUUID`。
2. `client_profile.json` 或默认配置里的 `device_profile.device_id`。

设备指纹还会使用 Cookie 中的 `DEVICEFP`。

### 3.2 Web 账号同步

账号同步由 `Dispatcher._sync_web_account()` 完成。

#### 3.2.1 `webVerifyForGame`

请求：

- URL：`WEB_VERIFY_URL`
- 方法：POST
- Body：`{}`
- 关键 Header：
  - `cookie`
  - `x-rpc-app_id: c90mr1bwo2rk`
  - `x-rpc-client_type: 25`
  - `x-rpc-device_id`
  - `x-rpc-device_fp`
  - `x-rpc-game_biz: hkrpg_cn`
  - `x-rpc-mi_referrer: https://sr.mihoyo.com/cloud/#/`
  - `x-rpc-sdk_version: 2.50.1`
  - `origin: https://sr.mihoyo.com`
  - `referer: https://sr.mihoyo.com/`

响应要求：

- `retcode == 0`
- `data.token.token` 存在，作为 `channel_token`。

#### 3.2.2 `webLogin`

请求：

- URL：`WEB_LOGIN_URL`
- 方法：POST
- Body：

```json
{"app_id":8,"channel_id":1}
```

- 关键 Header：
  - `cookie`
  - `x-rpc-app_id: 8`
  - `x-rpc-channel_id: 1`
  - `x-rpc-mdk_version: 2.49.0`
  - 其他 Web 设备和浏览器字段同上。

响应要求：

- `retcode == 0`
- `data` 中包含：
  - `app_id`
  - `channel_id`
  - `open_id`
  - `combo_token`

### 3.3 `x-rpc-combo_token`

`webLogin` 后，客户端重新包装 combo token：

```text
ai=<app_id>;ci=<channel_id>;oi=<open_id>;ct=<combo_token>;si=<signature>;bi=hkrpg_cn
```

`si` 的计算方式：

```text
signing_text = "&".join(f"{key}={payload[key]}" for key in sorted(payload))
signature = HMAC-SHA256(COMBO_APP_KEY, signing_text).hexdigest()
```

其中：

- `COMBO_APP_KEY = 4650f3a396d34d576c3d65df26415394`
- 签名 payload：
  - `app_id`
  - `channel_id`
  - `open_id`
  - `combo_token`

### 3.4 调度请求头

调度接口通用 Header：

| Header | 示例/来源 |
| --- | --- |
| `x-rpc-cg_game_biz` | `hkrpg_cn` |
| `x-rpc-op_biz` | `clgm_hkrpg-cn` |
| `x-rpc-app_id` | `8` |
| `x-rpc-channel` | `mihoyo` |
| `x-rpc-device_id` | `_MHYUUID` 或配置默认值 |
| `x-rpc-device_name` | `device_profile.device_name` |
| `x-rpc-language` | `zh-cn` |
| `x-rpc-app_version` | `browser_profile.app_version`，默认 `4.3.0` |
| `x-rpc-client_type` | `19` |
| `x-rpc-device_model` | `device_profile.model` |
| `x-rpc-cps` | `keyboard_mihoyo` |
| `x-rpc-sys_version` | `device_profile.sys_version` |
| `x-rpc-vendor_id` | `2` |
| `x-rpc-combo_token` | 账号同步生成值 |
| `cookie` | 米哈游登录 Cookie |
| `origin` | `https://sr.mihoyo.com` |
| `referer` | `https://sr.mihoyo.com/` |
| `user-agent` | 浏览器画像 |
| `sec-ch-ua` | 浏览器画像 |
| `sec-ch-ua-platform` | `"Linux"` |
| `sec-ch-ua-mobile` | `?0` |

### 3.5 调度签名

调度 API 体内的 `sign` 字段由 `APP_KEY` 计算：

```text
signing_text = "&".join(f"{key}={payload[key]}" for key in sorted(payload))
sign = HMAC-SHA256(APP_KEY, signing_text).hexdigest()
```

其中：

- `APP_KEY = 1fbf60a3582bf2ed05810954ee2349b9`
- 只对需要签名的基础字段签名，不包括最终请求体里额外添加的 `hint`、`net_state`、`queue_type`、`queue_switch`、`using_new_cmd_line` 等非签名字段。

### 3.6 调度流程

完整顺序：

1. `statusCheck`
   - Body：`{"biz_key":"hkrpg_cn"}`

2. `listPingServer`
   - Body：

```json
{"biz_key":"hkrpg_cn","ext_data":"{\"platform\":19}"}
```

3. `getNodesInfo`
   - Body：

```json
{"biz_key":"hkrpg_cn","node":"","speed_client_type":7}
```

4. 选择节点
   - 优先使用 `recommend == true` 的节点。
   - 没有推荐节点时使用第一个节点。

5. `preDispatchVerify`
   - 签名基础字段：
     - `biz_key`
     - `node_id`
     - `regions`：当节点存在 `region_ids` 时，为紧凑 JSON 字符串。
   - 实际 Body 中 `regions` 是数组。

6. `paasDispatch`
   - 见下一节。

7. 若 `result_code == FINISHED`
   - 直接使用 `data.finish_result`。

8. 若 `result_code == QUEUED`
   - 从 `data.queue_info.ticket` 构造 ticket payload。
   - 按 `queue_info.query_interval` 轮询 `getDispatchTicketInfo`。
   - 当 `ticket_status == SUCCESS` 时调用 `ackDispatchTicket`。
   - 使用 `ticket_info.data.finish_result`。

### 3.7 `paasDispatch` 请求体

签名基础字段：

| 字段 | 含义 | 默认值/来源 |
| --- | --- | --- |
| `bit_rate` | 目标码率 | `10240000` |
| `biz_key` | 业务 | `hkrpg_cn` |
| `cmd_line` | 额外命令行 | 空字符串 |
| `user_data` | 用户设备 JSON 字符串 | 见下 |
| `codec_type` | 编码类型 | `1` |
| `env` | 环境 | `2` |
| `ext_data` | 扩展数据 | 空字符串 |
| `fps` | 目标帧率 | `30` |
| `node_id` | 节点 ID | 选中节点 |
| `resolution` | 分辨率 | `1920x1080` |
| `regions` | 区域列表 JSON 字符串 | 节点有 `region_ids` 时 |

最终 Body：

```json
{
  "hint": null,
  "net_state": 4,
  "queue_type": "",
  "sign": "<hmac>",
  "using_new_cmd_line": true,
  "queue_switch": false,
  "bit_rate": 10240000,
  "biz_key": "hkrpg_cn",
  "cmd_line": "",
  "user_data": "<json-string>",
  "codec_type": 1,
  "env": "2",
  "ext_data": "",
  "fps": 30,
  "node_id": "<node_id>",
  "resolution": "1920x1080",
  "regions": []
}
```

`queue_type`：

- `""`：普通队列。
- `"coin"`：星云币优先队列。

### 3.8 `user_data` 与 `device_info`

`user_data` 是紧凑 JSON 字符串：

```json
{
  "dpi": 96,
  "w": 1920,
  "h": 1080,
  "lang": "zh-CN",
  "di": "<base64-json>"
}
```

`di` 解码后是：

```json
{
  "operationSystem": "Linux undefined",
  "deviceModel": "Unknown",
  "processorCount": 16,
  "processorFrequency": 16,
  "processorType": "Unknown",
  "systemMemorySize": 8,
  "DeviceSoC": "Unknown",
  "serial_number": "<device_id>_<account_id>"
}
```

## 4. `finish_result` 与 `sdk_param`

调度完成后，核心字段是：

```json
{
  "sdk_param": "<base64-protobuf>",
  "cloud_provider": "...",
  "region_id": "...",
  "node_id": "...",
  "queue_type": "...",
  "game_id": "..."
}
```

`sdk_param` 是 base64 编码的 `proto.paas.SdkStartGameParams`。官方 SDK 字段如下：

| Field | 名称 | 类型 | 含义 |
| --- | --- | --- | --- |
| 1 | `sid` | string | 会话 ID |
| 2 | `ca_id` | string | Cloud Agent ID |
| 3 | `pod_id` | string | Pod ID |
| 4 | `game_token` | string | 游戏会话 token |
| 5 | `resolution` | string | 分辨率，如 `1920x1080` |
| 6 | `target_fps` | int32 | 目标帧率 |
| 7 | `cmd_line` | string | 游戏启动命令行，含 `-aid <account_id>` |
| 8 | `game_svr_addr` | string | 游戏服务器地址，通常 `ip:port` |
| 9 | `rtc_udp_port` | uint32 | RTC UDP 端口 |
| 10 | `additional_game_svr_addrs` | repeated string | 备用服务器地址 |
| 11 | `game_server_wss_url` | string | RTC 信令 WebSocket base URL |
| 12 | `additional_game_server_wss_urls` | repeated string | 备用 RTC WSS |
| 13 | `big_isp` | uint32 | 大 ISP 标志 |
| 14 | `game_control_channel_url` | string | 独立游戏控制通道 URL |
| 15 | `additional_game_control_channel_urls` | repeated string | 备用控制通道 URL |
| 16 | `is_ipv6` | bool | IPv6 标志 |
| 17 | `game_svr_addr_ipv6` | string | IPv6 游戏服务器地址 |
| 18 | `rtc_udp_port_ipv6` | uint32 | IPv6 RTC UDP 端口 |
| 19 | `additional_game_svr_addrs_ipv6` | repeated string | IPv6 备用地址 |
| 20 | `game_server_wss_url_ipv6` | string | IPv6 RTC WSS |
| 21 | `additional_game_server_wss_urls_ipv6` | repeated string | IPv6 备用 RTC WSS |
| 22 | `game_control_channel_url_ipv6` | string | IPv6 控制通道 URL |
| 23 | `additional_game_control_channel_urls_ipv6` | repeated string | IPv6 备用控制通道 |

当前 Python 实现解析了 1-15 字段，并从 `cmd_line` 中用正则解析 `account_id`：

```text
(?:^|\s)-aid\s+([^\s]+)
```

RTC 信令地址：

```text
rtc_wss_url = game_server_wss_url.endswith("/rtc-sdk")
  ? game_server_wss_url
  : game_server_wss_url + "/rtc-sdk"
```

ICE candidate 地址改写使用：

- IP：`game_svr_addr` 的冒号前部分。
- 端口：`rtc_udp_port`。

## 5. WebSocket 外层帧

RTC 信令 WebSocket 传输的二进制消息有统一外层：

```text
uint32_be frame_type
uint32_be payload_len
bytes     payload
```

帧类型：

| 值 | 名称 | Payload |
| --- | --- | --- |
| 1 | `SIGNALING` | UTF-8 JSON，WebRTC offer/answer/candidate |
| 2 | `PROXY` | 云游戏 Packet |
| 3 | `HANDSHAKE` | UTF-8 JSON |
| 4 | `KEEPALIVE` | 官方 SDK 中保留，本项目未使用 |

连接建立后客户端发送：

1. `PROXY` + `StartGameReq`。
2. `HANDSHAKE` + JSON：

```json
{"client_type":"web","type":"client hello"}
```

## 6. 云游戏 Packet

`PROXY` 帧 payload 是官方 SDK 的 `Packet`。

### 6.1 二进制格式

```text
offset size  endian  field
0      2     -       magic head = 0x45 0x67
2      2     be      cmd_id
4      2     be      head_len
6      4     be      msg_len
10     N     -       PacketHead protobuf，长度 head_len
10+N   M     -       message protobuf，长度 msg_len
10+N+M 2     -       magic tail = 0x89 0xab
```

最小包长 12 字节。当前实现通常发送空 `PacketHead`，即 `head_len = 0`。

官方 SDK 中 `Packet.toUint8Array()` 也按上述格式写出：

- head：`69, 103`
- tail：`137, 171`
- `cmd_id/head_len/msg_len` 均为大端。

### 6.2 `PacketHead`

大多数客户端到云端的 RTC 包可以空 head。官方 SDK 的 `proto.msg.PacketHead` 字段包括：

| Field | 名称 | 类型 |
| --- | --- | --- |
| 1 | `packet_id` | uint32 |
| 2 | `rpc_id` | uint32 |
| 3 | `client_sequence_id` | uint32 |
| 4 | `enet_channel_id` | uint32 |
| 5 | `enet_is_reliable` | uint32 |
| 6 | `client_ts` | int64 |
| 11 | `user_id` | string |
| 12 | `user_ip` | uint32 |
| 13 | `user_session_id` | uint32 |
| 14 | `session_value1` | bytes |
| 15 | `session_value2` | bytes |
| 16 | `session_value3` | string |
| 17 | `session_value4` | int64 |
| 18 | `bid` | string |
| 19 | `ticket` | string |
| 20 | `game_id` | string |
| 21 | `recv_time_ms` | int64 |
| 22 | `rpc_begin_time_ms` | uint32 |
| 23 | `ext_map` | map<uint32,uint32> |
| 24 | `target_service` | uint32 |
| 25 | `source_service` | uint32 |
| 26 | `service_ip_map` | map<uint32,uint32> |
| 27 | `region_id` | string |
| 28 | `sid` | string |
| 29 | `account_uid` | string |
| 30 | `node_id` | string |
| 31 | `trace_seq` | string |
| 32 | `tag` | uint64 |
| 33 | `is_bind` | uint32 |
| 34 | `span_tracer` | bytes |
| 35 | `gatesvr_start_rand` | int64 |
| 36 | `application_id` | int64 |
| 37 | `real_application_id` | int64 |
| 38 | `platform` | uint64 |

## 7. RTC/Proxy 命令号

| Cmd ID | 名称 | 方向 | 说明 |
| --- | --- | --- | --- |
| 1900 | `ReliableMessageQueueData` | 双向 | SDK game-data 可靠消息 |
| 20001 | `StartGameReq` | C -> S | 启动游戏 |
| 20002 | `StartGameRsp` | S -> C | 启动响应 |
| 20005 | `StopGameRsp` | S -> C | 停止/退出响应 |
| 20008 | `RtcResumeReq` | C -> S | 恢复游戏 |
| 20010 | `RtcDataChannel` | 双向 | 输入、反馈、心跳通道消息 |
| 20014 | `RtcNotPlayingTips` | S -> C | 未操作提示 |
| 20015 | `RtcKeepPlaying` | C -> S | 继续游玩保活 |
| 20016 | `SdkStatsInfo` | C -> S | SDK 统计，当前实现未发送 |
| 20017 | `SdkDeviceInfo` | C -> S | 设备信息 |
| 20018 | `RtcGameStasReport` | S -> C | 游戏状态/统计 |
| 20021 | `RtcKeepaliveCfg` | C -> S | 未操作踢出/提示时间 |
| 20029 | `Heartbeat` | 双向/输入通道 | 输入通道心跳 |
| 20032 | `KeyFrameReq` | C -> S | 请求关键帧 |
| 20036 | `RtcSetGraphicsMode` | C -> S | 设置画质模式 |
| 20039 | `RtcSetBitrateMultiplier` | C -> S | 设置码率倍率 |

## 8. 关键消息字段

### 8.1 `StartGameReq`，Cmd `20001`

官方 `proto.msg.StartGameReq`：

| Field | 名称 | 类型 | 当前实现 |
| --- | --- | --- | --- |
| 1 | `game_token` | string | `sdk_param.game_token` |
| 2 | `aid` | string | 从 `cmd_line -aid` 解析 |
| 3 | `sdk_version` | string | `6.2.0.24` |
| 4 | `terminal_type` | uint32 | `10` |
| 5 | `offline_mock_info` | message | 未使用 |
| 6 | `sid` | string | `sdk_param.sid` |
| 7 | `pod_id` | string | `sdk_param.pod_id` |
| 8 | `has_rtc_connected` | int32 | Python 当前未发送 |
| 9 | `since_start_sec` | uint32 | 默认 `1` |
| 10 | `link_tasks_ms` | uint32 | 当前传 `200` |
| 11 | `mock_game_mode` | uint32 | 未使用 |
| 12 | `game_config` | `SdkGameConfig` | 当前发送空 message |

官方 SDK 中 `game_config` 常设置：

| Field | 名称 | 类型 |
| --- | --- | --- |
| 1 | `enable_wrapped_h265` | bool |
| 2 | `is_big_isp` | bool |

当前实现以空 message 占位字段 12，使 wire 上存在 `game_config`。

### 8.2 `RtcResumeReq`，Cmd `20008`

| Field | 名称 | 类型 |
| --- | --- | --- |
| 1 | `game_token` | string |

### 8.3 `RtcKeepPlaying`，Cmd `20015`

| Field | 名称 | 类型 |
| --- | --- | --- |
| 1 | `game_token` | string |

触发时机：

- 每 60 秒定时发送。
- 收到 `RtcNotPlayingTips` 后立即发送一次。

### 8.4 `RtcKeepaliveCfg`，Cmd `20021`

| Field | 名称 | 类型 | 默认 |
| --- | --- | --- | --- |
| 1 | `kickout_duration` | uint32 | `300000` ms |
| 2 | `tips_duration` | uint32 | `20000` ms |

### 8.5 `SdkDeviceInfo`，Cmd `20017`

官方字段：

| Field | 名称 | 类型 | 当前实现 |
| --- | --- | --- | --- |
| 1 | `game_token` | string | 是 |
| 2 | `sdk_version` | string | 是 |
| 3 | `terminal_type` | uint32 | 是 |
| 4 | `device_id` | string | 已发送，但当前值来自 `client_lib`，见备注 |
| 5 | `device_vendor` | string | 未发 |
| 6 | `device_name` | string | 是 |
| 7 | `device_cpu` | string | 未发 |
| 8 | `device_gpu` | string | 是 |
| 9 | `device_system` | string | 是 |
| 10 | `total_memory` | uint32 | 未发 |
| 11 | `screen_width` | uint32 | 是 |
| 12 | `screen_height` | uint32 | 是 |
| 13 | `device_soundcard` | string | 未发 |
| 14 | `device_dpi` | uint32 | 未发 |
| 15 | `network_type` | string | 未发 |
| 16 | `device_ppi` | uint32 | 未发 |
| 17 | `server_ip` | string | 是 |
| 18 | `display_driver` | string | 未发 |
| 19 | `is_fullscreen` | uint32 | 未发 |
| 20 | `transport_protocol` | string | `udp` |

备注：当前 Python 实现沿用早期逆向命名，把 field 4 作为 `client_lib`。官方 SDK 当前 protobuf 显示 field 4 是 `device_id`。当前实现可用，但字段语义与官方 SDK 不一致；如果后续兼容性变差，应优先按官方字段名校正。

### 8.6 `RtcSetGraphicsMode`，Cmd `20036`

| Field | 名称 | 类型 | 默认 |
| --- | --- | --- | --- |
| 1 | `mode` | uint32 | `0` |

### 8.7 `RtcSetBitrateMultiplier`，Cmd `20039`

| Field | 名称 | 类型 | 默认 |
| --- | --- | --- | --- |
| 1 | `multiplier` | float | `1.875` |

### 8.8 `Heartbeat`，Cmd `20029`

| Field | 名称 | 类型 |
| --- | --- | --- |
| 1 | `heartbeat_id` | uint32 |
| 2 | `send_timestamp` | int64，毫秒时间戳 |

当前实现每秒通过可用输入通道发送一个 `Heartbeat` Packet。

### 8.9 `KeyFrameReq`，Cmd `20032`

空消息。当前实现发送 answer 后延迟约 1 秒请求一次关键帧。

## 9. WebRTC 信令

`SIGNALING` 帧 payload 是 UTF-8 JSON。

### 9.1 收到 offer

服务端发送：

```json
{
  "type": "offer",
  "sdp": "..."
}
```

客户端行为：

1. `setRemoteDescription(offer)`
2. `createAnswer()`
3. `setLocalDescription(answer)`
4. 发送：

```json
{
  "type": "answer",
  "sdp": "..."
}
```

5. 延迟发送 `KeyFrameReq`。

### 9.2 ICE candidate

客户端本地 candidate 发送格式：

```json
{
  "type": "candidates",
  "candidate": "candidate:...",
  "sdp-mid": "...",
  "sdp-mline-index": 0
}
```

收到服务端 candidate 后，当前实现会用 `sdk_param` 改写地址：

- candidate protocol 为 `udp` 或 `tcp` 时：
  - `ip = sdk_param.game_svr_addr.split(':', 1)[0]`
  - `port = sdk_param.rtc_udp_port`

然后调用 `addIceCandidate()`。

### 9.3 启动配置发送时机

启动配置最多发送一次。触发条件：

- RTC DataChannel open。
- 或 ICE 状态变为 `connected` / `completed`。

发送顺序按官方网页 SDK 行为：

1. `RtcSetGraphicsMode`
2. `RtcSetBitrateMultiplier`
3. `RtcKeepaliveCfg`
4. `RtcResumeReq`
5. `SdkDeviceInfo`

这个顺序缺失或延后，可能导致云端停留在初始化状态。

## 10. 独立游戏控制通道

`sdk_param` 可能携带 `game_control_channel_url` 及备用 URL。主 WebSocket 的 `HANDSHAKE` 帧会返回：

```json
{"session_id":123456}
```

客户端随后尝试连接控制通道：

```text
wss://<game_control_channel_url>?sessionId=<session_id>
```

若原 URL 是 `http/https/ws/wss` 或无 scheme，当前实现统一使用 `wss`。

### 10.1 控制通道消息前缀

控制通道 WebSocket payload 第一字节为类型：

| 前缀 | 含义 | 后续 payload |
| --- | --- | --- |
| `0x00` | 控制包 | 云游戏 Packet，KCP 控制命令 |
| `0x01` | 数据包 | 云游戏 Packet，通常是 `RtcDataChannel` 或 `Heartbeat` |

### 10.2 KCP 控制命令

官方 SDK 中控制通道握手命令：

| Cmd ID | 名称 | 字段 |
| --- | --- | --- |
| 1250 | `KcpConnectSync` | field 1 `session_id` uint32 |
| 1251 | `KcpConnectSyncAck` | field 1 `session_id` uint32 |
| 1252 | `KcpConnectAck` | field 1 `session_id` uint32 |
| 1253 | `KcpPing` | field 1 `session_id` uint32 |
| 1254 | `KcpPong` | field 1 `session_id` uint32 |

当前握手流程：

1. 控制通道连接成功后，客户端发送 `0x00 + Packet(1250, {session_id})`。
2. 收到 `1251` 后发送 `0x00 + Packet(1252, {session_id})`。
3. 标记控制通道 ready。
4. 每 2 秒发送 `1253`。
5. 收到 `1254` 更新时间；超过 5 秒没有 pong 则关闭通道。

输入发送优先级：

1. 独立游戏控制通道可用：发送 `0x01 + Packet(...)`。
2. 控制通道不可用但 RTC DataChannel open：直接通过 DataChannel 发送 `Packet(...)`。
3. 两者都不可用：丢弃输入。

## 11. 输入协议 `RtcDataChannel`

输入包是 `Packet(cmd_id=20010, msg=RtcDataChannel)`。

官方 `proto.msg.RtcDataChannel`：

| Field | 名称 | 类型 |
| --- | --- | --- |
| 1 | `type` | enum `DataType` |
| 2 | `keyboard` | `RtcKeyboard` |
| 3 | `mouse` | `RtcMouse` |
| 4 | `mouse_feedback` | `RtcMouseFeedback` |
| 5 | `ime_input` | `RtcImeInput` |
| 6 | `ime_input_feedback` | `RtcImeInputFeedback` |
| 7 | `clipboard` | `RtcClipboard` |
| 8 | `clipboard_feedback` | `RtcClipboardFeedback` |
| 9 | `video_state` | `RtcVideoState` |
| 10 | `gamepad` | `RtcGamepadKey` |
| 11 | `gamepad_list` | `RtcGamepadList` |
| 12 | `gamepad_feedback` | `RtcGamepadFeedback` |
| 13 | `touch_list` | `RtcTouchEventList` |
| 14 | `imu_event` | `RtcImuEvent` |
| 15 | `imu_feedback` | `RtcImuFeedback` |
| 17 | `input_control_type` | uint32 |
| 18 | `message_trace_id` | uint64 |

### 11.1 `DataType`

| 值 | 名称 |
| --- | --- |
| 0 | `INVALID` |
| 1 | `KEYBOARD_DOWN` |
| 2 | `KEYBOARD_UP` |
| 3 | `MOUSE_MOVE` |
| 4 | `MOUSE_LBUTTON_DOWN` |
| 5 | `MOUSE_LBUTTON_UP` |
| 6 | `MOUSE_RBUTTON_DOWN` |
| 7 | `MOUSE_RBUTTON_UP` |
| 8 | `MOUSE_MBUTTON_DOWN` |
| 9 | `MOUSE_MBUTTON_UP` |
| 10 | `MOUSE_ZDELTA` |
| 11 | `MOUSE_FEEDBACK` |
| 12 | `IME_INPUT` |
| 13 | `IME_INPUT_FEEDBACK` |
| 14 | `IME_CLIPBOARD` |
| 15 | `IME_CLIPBOARD_FEEDBACK` |
| 16 | `VIDEO_STATE` |
| 17 | `GAMEPAD_KEY` |
| 18 | `GAMEPAD_LIST` |
| 19 | `GAMEPAD_FEEDBACK` |
| 20 | `GAME_STATS_REPORT` |

### 11.2 当前 Python 输入字段

当前实现使用了较小子集：

#### 鼠标

`RtcDataChannel`：

- field 1：`type`
- field 3：`mouse`

Python 编码的 `mouse` 字段：

| Field | 名称 | 类型 | 用途 |
| --- | --- | --- | --- |
| 1 | `x` / cursor x | double | 归一化坐标或 0 |
| 2 | `y` / cursor y | double | 归一化坐标或 0 |
| 3 | `wheel_delta` | double | 滚轮 |
| 4 | `dx` | double | 相对移动 x |
| 5 | `dy` | double | 相对移动 y |

说明：

- `move/down/up` 的 `x/y` 可传 0.0-1.0 归一化坐标。
- 若传像素坐标，当前实现会按 `sdk_param.resolution` 自动归一化。
- `scroll` 使用 `MOUSE_ZDELTA`，只填 `wheel_delta`。

#### 键盘

`RtcDataChannel`：

- field 1：`type = KEYBOARD_DOWN/KEYBOARD_UP`
- field 2：`keyboard`

`keyboard` 字段：

| Field | 名称 | 类型 |
| --- | --- | --- |
| 1 | `key_code` | uint32，Windows Virtual-Key |
| 4 | `capslock_toggled` | bool |
| 5 | `numlock_toggled` | bool |

官方 Web SDK 会把浏览器键盘事件翻译为 Windows VK。例如：

- `A-Z`：65-90
- `0-9`：48-57
- `Shift`：16，左右分别 160/161
- `Ctrl`：17，左右分别 162/163
- `Alt`：18，左右分别 164/165
- 方向键：37-40
- `F1-F12`：112-123

#### IME 文本

`RtcDataChannel`：

- field 1：`type = IME_INPUT`
- field 5：`ime_input`

`ime_input`：

| Field | 名称 | 类型 |
| --- | --- | --- |
| 1 | `text` | string |

#### 剪贴板

`RtcDataChannel`：

- field 1：`type = IME_CLIPBOARD`
- field 7：`clipboard`

`clipboard`：

| Field | 名称 | 类型 |
| --- | --- | --- |
| 1 | `text` | string |

## 12. RMQ 与 SDK game-data

游戏内 SDK 回调走 `ReliableMessageQueueData`，Cmd `1900`。

### 12.1 `ReliableMessageQueueData`

官方字段：

| Field | 名称 | 类型 |
| --- | --- | --- |
| 1 | `msg_id` | uint32 |
| 2 | `msg_type` | uint32 |
| 3 | `seq_id` | uint32 |
| 4 | `seq_cnt` | uint32 |
| 5 | `total_len` | uint32 |
| 6 | `data_len` | uint32 |
| 7 | `data` | bytes |
| 8 | `tag` | string |

`msg_type`：

| 值 | 含义 |
| --- | --- |
| 1 | 单包/普通数据 |
| 2 | 分片开始 |
| 3 | 分片后续 |
| 4 | ACK |

当前接收逻辑：

1. `msg_type == 4`：忽略。
2. `msg_type in (1,2,3)`：按 `total_len` 缓冲重组。
3. 重组完成后处理 SDK game-data。
4. 发送 ACK：
   - `ReliableMessageQueueAck` 实际只需 field 1 写入 `ack_msg_id`。
   - 外层 RMQ：`msg_type = 4`，`data = ack protobuf`。

### 12.2 `SdkGameDataMessage`

RMQ data 里是：

| Field | 名称 | 类型 |
| --- | --- | --- |
| 1 | `name` | string |
| 2 | `data` | bytes |

`name == "SDK"` 时，`data` 是 base64 文本，内容为 AES 加密 JSON。

### 12.3 SDK AES 加密

固定 AES key：

```text
OK20kydiRu47rOH7HNXzA12xxtlYVOUx
```

算法：

- AES-256-ECB
- PKCS#7 padding
- 密文再 base64

接收：

```text
json = AES-ECB-PKCS7-decrypt(base64_decode(data))
```

发送：

```text
data = base64_encode(AES-ECB-PKCS7-encrypt(compact_json))
```

### 12.4 SDK JSON 消息格式

常见入站消息：

```json
{
  "f": "invoke",
  "i": 123,
  "p": "{\"f\":\"login_login\",\"p\":\"...\"}"
}
```

常见响应格式：

```json
{
  "f": "on_get_invoke_response",
  "p": "{\"index\":123,\"data\":\"<json-or-string>\"}"
}
```

`p` 通常是字符串化 JSON；`data` 也经常是字符串化 JSON。

### 12.5 当前实现支持的 SDK 回调

#### 直接函数

| 函数 | 行为 |
| --- | --- |
| `cloud_get_clipboard_data` | 返回本地剪贴板文本 |
| `cloud_get_data` | 从内存 KV 读取 |
| `cloud_set_data` | 写入内存 KV |
| `invoke_return` | 解析嵌套函数并应答 |
| `invoke` / `invokeF` / `invokeP` | 解析嵌套函数并应答 |
| `webview` | 处理 WebView UA |

#### 登录

嵌套函数 `login_login` 返回：

```json
{
  "ret": 0,
  "msg": "成功",
  "data": {
    "device_id": "<device_id>",
    "app_id": 8,
    "channel_id": 1,
    "channel_token": "<channel_token>",
    "combo_id": "0",
    "open_id": "<open_id>",
    "combo_token": "<raw_combo_token>",
    "account_type": 1,
    "guest": false
  }
}
```

优先使用 HTTP 账号同步阶段生成的 `sdk_login`。

#### 协议/用户协议

嵌套函数：

- `launch_show_user_agreement_with_parameters`
- `launch_show_user_agreement_with_parameters_compliance`

返回：

```json
{
  "ret": 1,
  "msg": "成功",
  "data": {
    "is_show": false,
    "protocol": {
      "major": 13,
      "minimum": 0
    }
  }
}
```

#### 初始化

嵌套函数 `Init` 返回两条回调：

1. `on_set_box_config`

```json
{
  "save_image_loading": true,
  "save_image_time_out": "10",
  "get_clipboard_data_timeout": "3"
}
```

2. `on_init_response`

```json
{
  "index": -1,
  "data": "{\"ret\":0,\"msg\":\"mihoyo web sdk init success\"}"
}
```

#### 其他已兼容函数

| 函数 | 响应 |
| --- | --- |
| `info_get_cps` | `keyboard_mihoyo` |
| `info_get_uapc` | 空字符串 |
| `info_get_channel_id` | `"1"` |
| `info_get_sub_channel_id` | `"1"` |
| `cloud_keep_alive` | 空成功 |
| `get_disk_type` | function not found |
| `get_global_user_agent` | 配置中的 WebView UA |
| `set_global_user_agent` / `pre_load` | index < 0 时忽略 |
| `report_*` | index < 0 时忽略 |
| `all_set_env` 等设置类 | index < 0 时忽略 |

未知函数：

- 带 index 的 invoke 返回 `{"ret":-10,"msg":"function not found in ..."}`。
- 部分无 index/report 类消息直接忽略。

## 13. 会话运行状态机

当前实现的顺序可概括为：

```text
HTTP init
  -> webVerifyForGame
  -> webLogin
  -> build x-rpc-combo_token

dispatch
  -> statusCheck
  -> listPingServer
  -> getNodesInfo
  -> preDispatchVerify
  -> paasDispatch
  -> [poll ticket if queued]
  -> finish_result.sdk_param

session
  -> parse sdk_param
  -> connect rtc_wss_url
  -> send StartGameReq
  -> send HANDSHAKE client hello
  -> receive offer
  -> send answer
  -> receive handshake session_id
  -> connect game control channel
  -> receive/add candidates
  -> DataChannel open or ICE connected
  -> send startup config
  -> consume video/audio
  -> heartbeat loop
  -> keep playing loop
  -> handle RMQ SDK callbacks
```

## 14. 钱包与队列预估

### 14.1 钱包

接口：

```text
GET /wallet/wallet/get
```

可选 query：

- `cost_method`
- `get_type`

当前摘要字段：

| 字段 | 来源 |
| --- | --- |
| `coin_num` | `data.coin.coin_num` |
| `coin_exchange` | `data.coin.exchange`，默认 10 |
| `coin_minutes` | `coin_num // exchange` |
| `free_time_minutes` | `data.free_time.free_time` |
| `play_card_remaining_sec` | `data.play_card.remaining_sec` |
| `cost_method` | `data.cost_method` |
| `status` | `data.status` |

### 14.2 队列预估

队列预估复用：

1. `statusCheck`
2. `getNodesInfo`
3. `preDispatchVerify`

`preDispatchVerify.data` 中：

- `queue_info`：普通队列。
- `prior_queue_info`：星云币优先队列。

摘要字段：

| 字段 | 说明 |
| --- | --- |
| `queue_type` | 队列类型 |
| `queue_len` | 队列人数/长度 |
| `branch_queue_len` | 分支队列长度 |
| `queue_length` | 队列长度 |
| `queue_rank` | 当前排名 |
| `waiting_time_min` | 预计等待分钟 |
| `query_interval` | 轮询间隔 |

## 15. 配置画像

`client_profile.json` 可覆盖 `core.config.DEFAULT_CORE_CONFIG`。

### 15.1 `device_profile`

用于 HTTP 调度设备信息和 RTC `SdkDeviceInfo`：

- `device_id`
- `os`
- `model`
- `cpu_cores`
- `cpu_freq`
- `cpu_type`
- `memory_gb`
- `soc`
- `gpu_model`
- `screen_width`
- `screen_height`
- `dpi`
- `device_name`
- `sys_version`

### 15.2 `browser_profile`

用于 HTTP Header 和 WebSocket UA：

- `user_agent`
- `sec_ch_ua`
- `app_version`
- `web_device_name`
- `web_device_model`
- `web_device_os`

### 15.3 `protocol_profile`

- `client_lib`
- `sdk_webview_ua`

### 15.4 `session_profile`

- `graphics_mode`
- `bitrate_multiplier`
- `resolution`
- `fps`
- `bit_rate`

## 16. 实现差异和注意事项

1. **`SdkDeviceInfo` field 4 命名差异**
   - 官方 SDK 当前字段是 `device_id`。
   - 本项目当前把它作为 `client_lib` 写入。
   - 若后续出现兼容问题，应改为官方字段，同时另寻 `client_lib` 对应字段或移除。

2. **输入鼠标字段和官方 `RtcMouse` 命名存在差异**
   - 官方源码中不同版本/模块里可见 `cursorX/cursorY/cursorDx/cursorDy` 或 `cursorRelativeX/Y` 等命名。
   - 当前实现以实测可用的 double 字段 1-5 编码。

3. **官方 SDK 有更多统计、Gamepad、Touch、IMU、HEVC wrapped pipeline 支持**
   - 当前 Python 实现只覆盖连接、视频接收、基础输入和 SDK 登录回调。

4. **WebSocket TLS 当前禁用证书校验**
   - `connect_websocket()` 使用 `CERT_NONE`。
   - 这有利于逆向调试，但不是生产安全实践。

5. **协议字段默认值不发送**
   - protobuf proto3 风格下，0、空字符串、false 通常不会序列化。
   - 若服务端要求字段“存在但为空”，需要像 `StartGameReq.game_config` 一样显式发送空 message。


## 17. 代码索引

| 协议部分 | 实现位置 |
| --- | --- |
| HTTP 账号同步 | `core/dispatcher.py::_sync_web_account` |
| 调度签名 | `core/dispatcher.py::_sign` |
| Combo token 签名 | `core/dispatcher.py::_combo_signature` |
| 调度流程 | `core/dispatcher.py::run` |
| 钱包/队列 | `core/dispatcher.py::wallet_info`、`queue_estimate` |
| `sdk_param` 解析 | `core/protocol.py::sdk_params` |
| protobuf 简易编解码 | `core/protocol.py::Protocol` |
| Packet 封包 | `core/protocol.py::packet`、`parse_packet` |
| WS 外层帧 | `core/protocol.py::ws_frame`、`parse_ws_frame` |
| RTC 启动包 | `core/protocol.py::start_game_frame` |
| 启动配置包 | `core/protocol.py::graphics_mode`、`bitrate_multiplier`、`keepalive_config`、`resume`、`device_info` |
| RMQ | `core/protocol.py::encode_rmq`、`parse_rmq`、`rmq_ack_frame` |
| SDK AES | `core/protocol.py::decrypt_sdk_json`、`encrypt_sdk_json` |
| 输入编码 | `core/protocol.py::input_from_action` |
| WebSocket/WebRTC 状态机 | `core/session.py::GameSession` |
| SDK 回调应答 | `core/session.py::SdkGameDataHandler` |
| 独立控制通道 | `core/session.py::GameControlChannel` |
