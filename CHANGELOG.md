# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> 兼容政策：见 [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md)——破坏性变更只能在
> MAJOR；弃用至少保留 1 个 MINOR，并在 `Deprecated` 段登记替代写法与移除版本。
> 升级前请扫一眼 Removed / Changed / Deprecated 段。

## [1.0.0] - 2026-11-25

### Changed

- **版本线重置**：自本版本起以 1.0.0 重新开始版本线，git 提交历史同步重置为
  单基线提交。代码功能面与重置前最后一版（3.7.1）完全一致，此前 1.7.0–3.7.1
  的发布记录与逐版发行说明可在 PyPI 历史版本页查阅。安装注意：PyPI 上旧线
  3.7.1 仍然存在且版本号更高，`pip install wmshare` 会继续解析到 3.7.1——
  需要新线请显式指定 `pip install "wmshare==1.0.0"`，后续 1.x 版本号涨过
  3.7.1 前均需如此。
