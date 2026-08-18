# Project Agent Instructions

## General Principles

- 修改代码前先理解现有实现。
- 优先最小修改，而不是大规模重写。
- 除非明确要求，否则保持向后兼容。
- 不修改与任务无关的文件。
- 没有充分理由不要添加生产依赖。
- 不提交密码、Token、API Key、密钥或其他凭据。
- 不静默吞掉异常。
- 不通过删除或削弱测试来使测试通过。
- 不声称未实际运行的测试已经通过。

## Multi-Agent Workflow

对于非简单任务，优先采用：

1. explorer：探索代码库、调用链和相关测试。
2. architect：复杂任务进行架构分析和任务拆分。
3. implementer：在问题和方案明确后进行实现。
4. tester：实现完成后进行测试和回归验证。
5. reviewer：最后进行独立代码审查。

推荐执行流程：

explorer + architect
        ↓
     主 Agent
        ↓
   implementer
        ↓
 tester + reviewer
        ↓
     主 Agent

explorer 和 architect 可以并行。

tester 和 reviewer 可以并行。

避免让多个具有写权限的 Agent 同时修改相同文件。

适合并行的任务：
- 代码库探索
- 测试分析
- Bug triage
- 日志分析
- 安全审查
- 文档/API核查

多个 Agent 同时修改代码时应特别谨慎。

## Implementation

修改之前：

- 定位受影响模块
- 查看现有代码模式
- 查看相关测试
- 确定调用链和依赖

修改之后：

- 首先运行最相关的小范围测试
- 然后在可行时执行更广泛验证
- 报告执行过的命令和结果
- 如验证失败，不要隐藏

## Bug Fixing

修复 Bug 时：

1. 复现或确认失败现象。
2. 找出根因。
3. 实施最小且合理的修复。
4. 在可行时增加回归测试。
5. 验证原始问题已经解决。

如果已经知道根因，不要只修复表面症状。

## Code Review

Review 优先级：

1. Correctness
2. Security
3. Regression
4. Data integrity
5. Missing tests
6. Performance

纯样式问题属于低优先级，除非影响可维护性或正确性。

## Communication

报告结果时：

- 区分事实与假设
- 引用相关文件路径
- 如有可能指出具体符号或函数
- 如实报告失败命令
- 不隐藏不确定性