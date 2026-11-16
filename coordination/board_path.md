# board 数据库的真实路径

**唯一真实路径由代码决定**：`coordination.paths.board_path()` 返回
`<主工作树>/out/subai/coordination/board.db`（当前 90 KB 级，是真库）。

## `coordination/board.db` 是什么

它是**0 字节的废弃空壳**，历史遗留，不承载任何数据。

- 任何模块**不得**以它为状态源；
- 任何模块**不得**读取它（`status --check` 的 C8 会扫这一条）；
- 保留它而不删除，是为了让「路径写错」这件事**看得见**，而不是悄悄换成一个空库继续跑。

## 为什么会有两份

早期实现把 board 放在包目录里（`coordination/board.db`），后来状态库迁到工作的 `out/subai/`（`paths.board_path()`），空壳没有清理。真实库的路径只认函数，不认路径字面量。
