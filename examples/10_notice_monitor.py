"""公告变更订阅：notice_poller 轮询器的手动一轮、ack 语义与进度重置。

前提：凭证可选——无凭证自动免注册免费试用（真实数据、需网络）
运行：python examples/10_notice_monitor.py
学到：poll_now 手动轮询（探针→拉新→回调→ack）；at-least-once（ack 前崩溃会重投）；StreamResetError→seek_oldest
文档：docs/GUIDE.md（公告变更订阅）
"""
import wmshare


def main(cli=None) -> None:
    if cli is None:
        cli = wmshare.Client.from_env()

    def on_events(events) -> None:
        for ev in events:
            print(f"  [{ev.market}] {ev.code} {ev.name}｜{ev.title}（{ev.date}）")
            print(f"      seq={ev.seq}  {ev.url}")

    # 消费进度按 (group, consumer) 存服务端：换进程续跑接着上次的进度走
    poller = cli.notice_poller(group="my-app", consumer="worker-1", on_events=on_events)

    print("--- 手动轮询一轮：探针 → 逐市场拉新 → 回调 → ack ---")
    delivered = poller.poll_now()
    print(f"本轮交付 {len(delivered)} 条")

    print("--- 再轮询一轮：进度已 ack，无新公告则不重投 ---")
    print(f"本轮交付 {len(poller.poll_now())} 条")

    # 生产模式：后台 daemon 线程定时轮询，退出时 stop()
    #   poller.start()
    #   try:
    #       ...干别的活...
    #   finally:
    #       poller.stop()
    print("--- 进度重置：进度超服务端保留期会抛 StreamResetError，按提示 seek_oldest() 重置 ---")
    print(f"seek_oldest('cn') → 光标重置到 {poller.seek_oldest('cn')}")


if __name__ == "__main__":
    try:
        main()
    except wmshare.WmshareError as e:
        print(f"订阅失败：{e}")
        raise SystemExit(1)
