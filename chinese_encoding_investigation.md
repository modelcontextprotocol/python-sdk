# Chinese Character Encoding Investigation

## Issue Description
GitHub Issue: Chinese conversion garbled characters

**Original Report**: When tool output contains Chinese, the client output is garbled.

## Investigation Results

### Current State ✅
**Chinese character encoding is working correctly** in the current MCP Python SDK implementation.

### Test Results

#### 1. Existing Unicode Tests
- ✅ `tests/client/test_http_unicode.py` - **PASSES**
  - Comprehensive Unicode tests including Chinese characters (你好世界 - 这是一个测试)
  - Tests both HTTP transport and tool calls
  - All tests pass successfully

#### 2. New Stdio Transport Tests
- ✅ `tests/issues/test_chinese_character_encoding.py` - **PASSES**
  - Tests Chinese characters through stdio transport specifically
  - Tests multiple Chinese character sets:
    - Simplified Chinese: 你好世界
    - Traditional Chinese: 繁體中文
    - Mixed content: Hello 世界 - 这是测试
    - Special punctuation: 【测试】「引号」『书名号』
    - Long text with various punctuation
    - Emoji with Chinese: 🈶️中文🈯️测试🈲️
  - All test cases pass without corruption

#### 3. Real-world Reproduction Test
- ✅ `reproduce_chinese_issue.py` - **PASSES**
  - Simulates actual client-server communication with Chinese text
  - Tests different encoding error handlers (strict, replace)
  - All Chinese characters preserved correctly in both directions

### Technical Implementation

The MCP Python SDK correctly handles Chinese character encoding through:

1. **UTF-8 Default Encoding** (`src/mcp/client/stdio/__init__.py:108`):
   ```python
   encoding: str = "utf-8"
   ```

2. **Explicit UTF-8 Stream Wrapping** (`src/mcp/server/stdio.py:89-92`):
   ```python
   stdin = anyio.wrap_file(TextIOWrapper(sys.stdin.buffer, encoding="utf-8"))
   stdout = anyio.wrap_file(TextIOWrapper(sys.stdout.buffer, encoding="utf-8"))
   ```

3. **UTF-8 JSON Response Encoding** (`src/mcp/server/auth/json_response.py:23`):
   ```python
   return content.model_dump_json(exclude_none=True).encode("utf-8")
   ```

4. **Configurable Encoding Error Handlers**:
   - `strict`: Fail on encoding errors (default)
   - `replace`: Replace invalid characters
   - `ignore`: Skip invalid characters

### Possible Causes for Original Issue

Since the current implementation works correctly, the original issue might have been caused by:

1. **Environment-specific problems**:
   - Incorrect system locale settings (LC_ALL, LANG)
   - Terminal emulator encoding issues
   - Platform-specific character rendering problems

2. **Older SDK versions**:
   - The issue may have been fixed in a previous update
   - UTF-8 handling improvements over time

3. **Configuration issues**:
   - Incorrect encoding parameters in client setup
   - System default encoding not being UTF-8

4. **Platform differences**:
   - Windows-specific character handling issues
   - Console output encoding problems

### Recommendations

1. **For users experiencing issues**:
   - Verify system locale is set to UTF-8: `export LC_ALL=en_US.UTF-8`
   - Check terminal emulator encoding settings
   - Update to latest MCP Python SDK version
   - Test with the provided reproduction script

2. **For developers**:
   - Use UTF-8 encoding explicitly when creating servers
   - Test Unicode content with the provided test cases
   - Consider terminal/console encoding when displaying output

### Test Files Added

1. `tests/issues/test_chinese_character_encoding.py` - Comprehensive Chinese character tests
2. `reproduce_chinese_issue.py` - Simple reproduction script for debugging

### Conclusion

The Chinese character encoding issue appears to be **resolved** in the current implementation. The MCP Python SDK properly handles Chinese characters in both client-server communication and tool outputs. The comprehensive test suite demonstrates that Chinese text is preserved correctly through both HTTP and stdio transports.

If users are still experiencing this issue, it's likely due to environment-specific factors rather than the MCP SDK itself.