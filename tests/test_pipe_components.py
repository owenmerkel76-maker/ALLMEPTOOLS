"""Run shipped component-tag functions against a small transactional host.

These regressions verify reference/type proof, rollback, and truthful counts;
they do not claim tag-family loading or a Revit integration test.
"""
import ast
import time
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ROBMEPTOOLS.extension/ROBMEPTOOLS.tab/AutoTag.panel/AutoTag Smart.pushbutton/autotag_components.py"


class ElementId(int):
    @property
    def Value(self):
        return int(self)

    @property
    def IntegerValue(self):
        return int(self)


class RegenerationFailedException(Exception):
    def GetType(self):
        return SimpleNamespace(FullName="Autodesk.Revit.Exceptions.RegenerationFailedException")


class Reference:
    def __init__(self, element):
        self.ElementId = element.Id


class Tag:
    def __init__(self, doc, tag_id, source_id, type_id=70, view_id=1, orphan=False):
        self.doc = doc
        self.Id = ElementId(tag_id)
        self.OwnerViewId = ElementId(view_id)
        self.type_id = ElementId(type_id)
        self.source_ids = [ElementId(source_id)]
        self.IsOrphaned = orphan
        self.HasLeader = True
        self.change_type = None

    def GetTypeId(self):
        return self.type_id

    def GetTaggedLocalElementIds(self):
        return self.source_ids

    def ChangeTypeId(self, type_id):
        if self.change_type is not None:
            return self.change_type(self, type_id)
        self.type_id = type_id
        return ElementId(-1)


class Document:
    def __init__(self):
        self.elements = {}
        self.transactions = []
        self.on_commit = None
        self.read_ids = []

    def GetElement(self, element_id):
        self.read_ids.append(int(element_id))
        return self.elements.get(int(element_id))


class Transaction:
    def __init__(self, doc, name=None):
        self.doc = doc
        self.name = name
        self.events = []
        self.snapshot = None
        doc.transactions.append(self)

    def Start(self):
        self.events.append("start")
        self.snapshot = dict(self.doc.elements)

    def Commit(self):
        self.events.append("commit")
        if self.name is not None and self.doc.on_commit is not None:
            self.doc.on_commit(self.doc)

    def RollBack(self):
        self.events.append("rollback")
        self.doc.elements = dict(self.snapshot)


class Collector:
    def __init__(self, doc, view_id):
        self.doc = doc
        self.category = None
        self.tags = False

    def OfClass(self, tag_class):
        self.tags = True
        return self

    def OfCategory(self, category):
        self.category = category
        return self

    def WhereElementIsNotElementType(self):
        if self.tags:
            return [elem for elem in self.doc.elements.values() if isinstance(elem, Tag)]
        return [elem for elem in self.doc.elements.values()
                if getattr(elem, "category", None) == self.category]


class CreationApi:
    """Model both seven-argument Revit Create overloads and new-element leaks."""
    def __init__(self, doc):
        self.doc = doc
        self.calls = []
        self.steps = []
        self.next_id = 100

    def Create(self, *args):
        self.calls.append(args)
        if self.steps:
            step = self.steps.pop(0)
            if isinstance(step, Exception):
                raise step
            return step(args)
        typed = isinstance(args[2], ElementId)
        view_id = args[2] if typed else args[1]
        source_id = args[3].ElementId if typed else args[2].ElementId
        type_id = args[1] if typed else ElementId(999)
        return self.new_tag(source_id, type_id, view_id)

    def new_tag(self, source_id=10, type_id=70, view_id=1, orphan=False):
        tag = Tag(self.doc, self.next_id, source_id, type_id, view_id, orphan)
        self.next_id += 1
        self.doc.elements[int(tag.Id)] = tag
        return tag


class PipeComponentTests(unittest.TestCase):
    def setUp(self):
        self.doc = Document()
        self.view = SimpleNamespace(Id=ElementId(1))
        self.elem = SimpleNamespace(Id=ElementId(10), category="fixture", point=object())
        self.doc.elements[10] = self.elem
        self.api = CreationApi(self.doc)
        db = SimpleNamespace(
            ElementId=ElementId, Reference=Reference,
            IndependentTag=SimpleNamespace(Create=self.api.Create),
            TagOrientation=SimpleNamespace(Horizontal="horizontal"),
            TagMode=SimpleNamespace(TM_ADDBY_CATEGORY="category"),
            BuiltInCategory=SimpleNamespace(OST_PlumbingFixtures="fixture", OST_DuctTerminal="fixture"),
            FilteredElementCollector=Collector, Transaction=Transaction,
            SubTransaction=Transaction,
        )
        self.ns = {
            "DB": db, "System": SimpleNamespace(Int64=int), "time": time,
            "_center": lambda elem, view: elem.point,
            "_project_to_view_plane": lambda point, view: point,
        }
        names = {"_eid_value", "_tagged_ids", "_tag_matches_component", "_is_regeneration_failure",
                 "_create_tag", "_collect", "_failure", "run_direct_component_tags"}
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
        found = set()
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in names:
                self.ns.setdefault('Int64', int)
                exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), self.ns)
                found.add(node.name)
        self.assertEqual(names, found, "Tests must execute shipped component functions")

    def run_components(self, discipline="pipe"):
        return self.ns["run_direct_component_tags"](
            self.doc, self.view, None, discipline,
            {"components": {"terminal": True}, "tag_types": {"terminal": {"id": 70}}})

    def existing_tag(self, **kwargs):
        tag = Tag(self.doc, 90, 10, **kwargs)
        self.doc.elements[90] = tag
        return tag

    def tags(self):
        return [elem for elem in self.doc.elements.values() if isinstance(elem, Tag)]

    def test_pipe_duplicate_requires_selected_type_host_view_and_nonorphan(self):
        for mismatch in ("none", "type", "host", "view", "orphan"):
            with self.subTest(mismatch=mismatch):
                self.setUp()
                tag = self.existing_tag()
                if mismatch == "type":
                    tag.type_id = ElementId(71)
                elif mismatch == "host":
                    tag.source_ids = [ElementId(11)]
                elif mismatch == "view":
                    tag.OwnerViewId = ElementId(2)
                elif mismatch == "orphan":
                    tag.IsOrphaned = True
                result = self.run_components()
                if mismatch == "none":
                    self.assertEqual((0, 1, 0), (result["created"], result["skipped"], result["failed"]))
                    self.assertEqual([], self.api.calls)
                else:
                    self.assertEqual((1, 0, 0), (result["created"], result["skipped"], result["failed"]))
                    self.assertEqual(1, len(self.api.calls))

    def test_duct_any_host_tag_suppression_is_unchanged(self):
        self.existing_tag(type_id=71, orphan=True)
        result = self.run_components("duct")
        self.assertEqual((0, 1, 0), (result["created"], result["skipped"], result["failed"]))
        self.assertEqual([], self.api.calls)
        self.assertEqual(1, len(self.doc.transactions))

    def test_pipe_rejected_create_rolls_back_subtransaction_without_a_leaked_tag(self):
        for reason in ("wrong-type", "wrong-source", "wrong-view", "orphan"):
            with self.subTest(reason=reason):
                self.setUp()
                def create_invalid(args):
                    return self.api.new_tag(source_id=11 if reason == "wrong-source" else 10,
                                            type_id=71 if reason == "wrong-type" else 70,
                                            view_id=2 if reason == "wrong-view" else 1,
                                            orphan=reason == "orphan")
                self.api.steps = [create_invalid]
                result = self.run_components()
                self.assertEqual((0, 0, 1), (result["created"], result["skipped"], result["failed"]))
                self.assertEqual([], result["created_ids"])
                self.assertEqual([], result["created_records"])
                self.assertEqual([], self.tags())
                self.assertEqual(["start", "rollback"], self.doc.transactions[1].events)
                self.assertEqual(["start", "commit"], self.doc.transactions[0].events)

    def test_failed_type_change_rolls_back_default_type_tag(self):
        def default_with_failed_type_change(args):
            tag = self.api.new_tag(type_id=999)
            def fail(tag, requested):
                raise RuntimeError("family type is incompatible")
            tag.change_type = fail
            return tag
        self.api.steps = [TypeError("typed overload unavailable"), default_with_failed_type_change]
        result = self.run_components()
        self.assertEqual(2, len(self.api.calls))
        self.assertEqual(0, result["created"])
        self.assertEqual(1, result["failed"])
        self.assertEqual([], self.tags())
        self.assertEqual(["start", "rollback"], self.doc.transactions[1].events)
        self.assertIn("incompatible", result["failures"][0][2])

    def test_change_type_replacement_element_id_is_resolved_and_counted(self):
        def default_with_replacement(args):
            tag = self.api.new_tag(type_id=999)
            def replace(old, requested):
                new = self.api.new_tag(source_id=10, type_id=requested)
                del self.doc.elements[int(old.Id)]
                return new.Id
            tag.change_type = replace
            return tag
        self.api.steps = [TypeError("typed overload unavailable"), default_with_replacement]
        result = self.run_components()
        self.assertEqual(1, result["created"])
        self.assertEqual([101], result["created_ids"])
        self.assertEqual(10, result["created_records"][0]["source_id"])
        self.assertEqual(70, result["created_records"][0]["type_id"])
        self.assertNotIn(100, self.doc.elements)
        self.assertEqual(False, self.doc.elements[101].HasLeader)

    def test_post_commit_vanished_or_wrong_reference_tag_is_excluded_from_counts(self):
        for change in ("vanished", "source", "type", "view", "orphan"):
            with self.subTest(change=change):
                self.setUp()
                def mutate(doc):
                    tag = self.tags()[0]
                    if change == "vanished":
                        del doc.elements[int(tag.Id)]
                    elif change == "source":
                        tag.source_ids = [ElementId(11)]
                    elif change == "type":
                        tag.type_id = ElementId(71)
                    elif change == "view":
                        tag.OwnerViewId = ElementId(2)
                    else:
                        tag.IsOrphaned = True
                self.doc.on_commit = mutate
                result = self.run_components()
                self.assertEqual(0, result["created"])
                self.assertEqual(1, result["failed"])
                self.assertEqual(1, result["post_commit_rejected"])
                self.assertEqual([], result["created_ids"])
                self.assertEqual([], result["created_records"])
                subtotal = result["by_category"]["Plumbing fixtures"]
                self.assertEqual((0, 1), (subtotal["created"], subtotal["failed"]))

    def test_regeneration_failure_stops_typed_overload_fallback_and_rolls_back(self):
        failure = RegenerationFailedException("document is corrupted")
        self.api.steps = [failure]
        with self.assertRaises(RegenerationFailedException) as caught:
            self.run_components()
        self.assertIs(failure, caught.exception)
        self.assertEqual(1, len(self.api.calls), "Do not try a second overload after fatal regeneration")
        self.assertEqual([], self.tags())
        self.assertEqual(["start", "rollback"], self.doc.transactions[1].events)
        self.assertEqual(["start", "rollback"], self.doc.transactions[0].events)

    def test_regeneration_failure_in_fallback_create_propagates_and_rolls_back(self):
        failure = RegenerationFailedException("default overload regeneration failed")
        self.api.steps = [TypeError("typed overload unavailable"), failure]
        with self.assertRaises(RegenerationFailedException) as caught:
            self.run_components()
        self.assertIs(failure, caught.exception)
        self.assertEqual(2, len(self.api.calls))
        self.assertEqual([], self.tags())
        self.assertEqual(["start", "rollback"], self.doc.transactions[0].events)

    def test_regeneration_failure_during_type_change_cleans_default_tag_and_propagates(self):
        failure = RegenerationFailedException("type change regeneration failed")
        def default_with_fatal_change(args):
            tag = self.api.new_tag(type_id=999)
            def fail(tag, requested):
                raise failure
            tag.change_type = fail
            return tag
        self.api.steps = [TypeError("typed overload unavailable"), default_with_fatal_change]
        with self.assertRaises(RegenerationFailedException) as caught:
            self.run_components()
        self.assertIs(failure, caught.exception)
        self.assertEqual([], self.tags())
        self.assertEqual(["start", "rollback"], self.doc.transactions[1].events)
        self.assertEqual(["start", "rollback"], self.doc.transactions[0].events)

    def test_regeneration_failure_setting_leader_aborts_before_commit_or_more_reads(self):
        failure = RegenerationFailedException("leader regeneration failed")
        class FatalLeaderTag(Tag):
            @property
            def HasLeader(self):
                return self._leader

            @HasLeader.setter
            def HasLeader(self, value):
                if value is False:
                    raise failure
                self._leader = value

        def create(args):
            tag = FatalLeaderTag(self.doc, 100, 10)
            self.doc.elements[100] = tag
            return tag
        self.api.steps = [create]
        with self.assertRaises(RegenerationFailedException) as caught:
            self.run_components()
        self.assertIs(failure, caught.exception)
        self.assertEqual([], self.tags())
        self.assertEqual([], self.doc.read_ids, "Do not read a corrupted document after leader failure")
        self.assertEqual(1, len(self.api.calls))
        self.assertEqual(["start", "rollback"], self.doc.transactions[1].events)
        self.assertEqual(["start", "rollback"], self.doc.transactions[0].events)

    def test_fatal_existing_host_read_stops_reference_fallback_before_mutation(self):
        failure = RegenerationFailedException("existing tag host read failed")
        fallback_calls = []
        class FatalHostTag(Tag):
            def GetTaggedLocalElementIds(self):
                raise failure

            def GetTaggedReferences(self):
                fallback_calls.append(True)
                return []
        self.doc.elements[90] = FatalHostTag(self.doc, 90, 10)
        with self.assertRaises(RegenerationFailedException) as caught:
            self.run_components()
        self.assertIs(failure, caught.exception)
        self.assertEqual([], fallback_calls)
        self.assertEqual([], self.api.calls)
        self.assertEqual([], self.doc.transactions)

    def test_duct_external_layout_callback_keeps_real_leader_and_audits_source(self):
        def place(tag, elem, label, point):
            tag.HasLeader = True
            return {'has_leader': True, 'layout_kind': 'external-component',
                    'head_bounds_phase': 'estimated-text-footprint'}
        place.release = lambda tag_id: None
        stats = self.ns['run_direct_component_tags'](
            self.doc, self.view, None, 'duct',
            {'components': {'terminal': True}, 'tag_types': {'terminal': {'id': 70}}},
            layout_handler=place)
        self.assertEqual(1, stats['created'])
        self.assertEqual(1, stats['external_leader_layouts'])
        self.assertEqual([100], stats['created_ids'])
        self.assertTrue(self.doc.elements[100].HasLeader)
        self.assertEqual('external-component', stats['created_records'][0]['layout_kind'])

    def test_duct_no_clear_component_position_rolls_back_new_tag_without_overlay(self):
        def place(*args):
            raise ValueError('No clear external position')
        stats = self.ns['run_direct_component_tags'](
            self.doc, self.view, None, 'duct',
            {'components': {'terminal': True}, 'tag_types': {'terminal': {'id': 70}}},
            layout_handler=place)
        self.assertEqual(0, stats['created'])
        self.assertEqual(1, stats['failed'])
        self.assertEqual({10}, set(self.doc.elements))

    def test_fatal_category_collection_is_not_reported_as_an_empty_success(self):
        failure = RegenerationFailedException("category collection failed")
        class FatalCollector(Collector):
            def WhereElementIsNotElementType(self):
                raise failure
        self.ns["DB"].FilteredElementCollector = FatalCollector
        with self.assertRaises(RegenerationFailedException) as caught:
            self.run_components()
        self.assertIs(failure, caught.exception)
        self.assertEqual([], self.api.calls)
        self.assertEqual([], self.doc.transactions)


if __name__ == "__main__":
    unittest.main()
