from sentry.grouping.component import GroupingComponent


def get_component_taxonomy(
    self, values, parent_child_components, parent_child_pairs, parent_child_ids
):
    # Put these at the top level of `component.py`
    # from collections import defaultdict
    # parent_child_components = defaultdict(set)
    # parent_child_pairs = set()
    # parent_child_ids = set()

    # Put this in `GroupingComponent.update`
    if values:
        for value in values:
            # Notice any types we're not accouting for in `child` below
            if (
                not isinstance(value, GroupingComponent)
                and not isinstance(value, str)
                and not isinstance(value, int)
            ):
                breakpoint()
            child = (
                "<str>"
                if isinstance(value, str)
                else "<int>" if isinstance(value, int) else value.id
            )
            parent_child_components[self.id].add(child)
            parent_child_pairs.add((self.id, child))
            parent_child_ids.add(self.id)
            parent_child_ids.add(child)

    # Fiddle with this number until it is the highest value at which the debugger still engages
    if len(parent_child_pairs) > 44:
        components_value_to_jsonify = {
            parent: sorted(child) for parent, child in parent_child_components.items()
        }
        is_value_to_jsonify = sorted(parent_child_ids)
        pairs_value_to_jsonify = sorted(list(pair) for pair in parent_child_pairs)
        breakpoint()

    assert 1 == 1
