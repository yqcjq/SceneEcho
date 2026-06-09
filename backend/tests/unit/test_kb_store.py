"""Phase 1B · KB store CRUD + IR round-trip unit tests."""

from __future__ import annotations

from app.ir.template import CaptionStyle, Slot, StyleRule, Tags, TemplateIR
from app.kb import store as kb_store


def _sample_ir(template_id: str = "tpl_test_1") -> TemplateIR:
    return TemplateIR(
        id=template_id,
        name="测试模板",
        source_sample="smp_xxx",
        skeleton=[
            Slot(
                role="开头",
                duration={"min": 1.4, "nominal": 2.0, "max": 3.0},
                material_req="人物口播",
                style=StyleRule(caption=CaptionStyle(size=64)),
            ),
            Slot(
                role="主体",
                duration={"min": 4.0, "nominal": 6.0, "max": 9.0},
                material_req="人物口播",
                style=StyleRule(),
            ),
        ],
        tags=Tags(function="强调推销", scene="纯口播", position="中间", notes="测试"),
        degraded={"audio": "Demucs unavailable"},
    )


def test_save_then_get_round_trip(temp_data_root):
    kb_store.init_db()
    ir = _sample_ir("tpl_round_trip")
    tid = kb_store.save_template(ir, last_extract_task_id="task_abc")
    assert tid == "tpl_round_trip"
    fetched = kb_store.get_template(tid)
    assert fetched is not None
    # IR survives JSON round-trip with degraded + skeleton intact.
    assert fetched["ir"]["skeleton"][0]["material_req"] == "人物口播"
    assert fetched["ir"]["degraded"]["audio"] == "Demucs unavailable"
    assert fetched["tags"]["function"] == "强调推销"
    assert fetched["last_extract_task_id"] == "task_abc"


def test_list_orders_newest_first(temp_data_root):
    kb_store.init_db()
    import time as _t

    kb_store.save_template(_sample_ir("tpl_list_a"))
    _t.sleep(0.01)
    kb_store.save_template(_sample_ir("tpl_list_b"))
    rows = kb_store.list_templates()
    ids = [r["id"] for r in rows]
    # Newest first — tpl_list_b inserted second so it should lead.
    pos_b = ids.index("tpl_list_b")
    pos_a = ids.index("tpl_list_a")
    assert pos_b < pos_a


def test_save_replaces_on_same_id(temp_data_root):
    kb_store.init_db()
    kb_store.save_template(_sample_ir("tpl_dup"))
    ir2 = _sample_ir("tpl_dup")
    ir2.name = "改名后"
    kb_store.save_template(ir2)
    fetched = kb_store.get_template("tpl_dup")
    assert fetched["name"] == "改名后"
    # Only one row should exist for this id.
    rows = kb_store.list_templates()
    assert len([r for r in rows if r["id"] == "tpl_dup"]) == 1


def test_update_tags_patches_both_columns(temp_data_root):
    kb_store.init_db()
    kb_store.save_template(_sample_ir("tpl_tags"))
    new_tags = Tags(function="教学讲解", scene="口播+B-roll", position="顶部", notes="update")
    ok = kb_store.update_template_tags("tpl_tags", new_tags)
    assert ok is True
    fetched = kb_store.get_template("tpl_tags")
    assert fetched["tags"]["function"] == "教学讲解"
    # Ensure the embedded ir_json was updated too (not just the convenience col).
    assert fetched["ir"]["tags"]["function"] == "教学讲解"


def test_update_caption_placeholder_writes_into_caption_style(temp_data_root):
    kb_store.init_db()
    kb_store.save_template(_sample_ir("tpl_ph"))
    ok = kb_store.update_caption_placeholder("tpl_ph", 0, ["立即抢购", "限时优惠"])
    assert ok is True
    fetched = kb_store.get_template("tpl_ph")
    assert fetched["ir"]["skeleton"][0]["style"]["caption"][
        "placeholder_text"
    ] == ["立即抢购", "限时优惠"]


def test_update_caption_placeholder_rejects_no_caption_slot(temp_data_root):
    kb_store.init_db()
    kb_store.save_template(_sample_ir("tpl_no_cap"))
    # Slot index 1 has no caption per _sample_ir.
    ok = kb_store.update_caption_placeholder("tpl_no_cap", 1, ["x"])
    assert ok is False


def test_delete_template_removes_row(temp_data_root):
    kb_store.init_db()
    kb_store.save_template(_sample_ir("tpl_del"))
    assert kb_store.delete_template("tpl_del") is True
    assert kb_store.get_template("tpl_del") is None
    assert kb_store.delete_template("tpl_del") is False
