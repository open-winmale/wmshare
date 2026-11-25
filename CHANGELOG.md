# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> 兼容政策：见 [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md)——破坏性变更只能在
> MAJOR；弃用至少保留 1 个 MINOR，并在 `Deprecated` 段登记替代写法与移除版本。
> 升级前请扫一眼 Removed / Changed / Deprecated 段。

## [4.0.0] - 2026-11-25

### Changed

- **版本线重置（MAJOR）**：自本版本起仓库提交历史重置为单基线提交；版本号在
  旧线末版 3.7.1 之上叠加 MAJOR 至 4.0.0，已安装用户 `pip install -U wmshare`
  可正常升级，无版本号回退歧义。代码功能面与 3.7.1 完全一致，此前 1.7.0–3.7.1
  的发布记录与逐版发行说明可在 PyPI 历史版本页查阅。
