function getMergeOrders(total) {
	const orders = [{
		order: "before",
		index: 0
	}];
	for (let index = 0; index < total; index++) {
		orders.push({
			order: "merge",
			index
		});
		orders.push({
			order: "after",
			index
		});
	}
	return orders;
}
/**
* Merge arrays of items
*/
function mergeArrays(list1, list2, merge) {
	if (!list1.length) return [list2];
	if (!list2.length) return [list1];
	function appendRemaining(queue) {
		return queue.filter((o) => o.order === "merge").map((o) => list1[o.index]);
	}
	function next(before, list2, queue) {
		const prev = [...before];
		const results = [];
		const currentItem = list2[0];
		const nextItems = list2.slice(1);
		for (let i = 0; i < queue.length; i++) {
			const orderItem = queue[i];
			switch (orderItem.order) {
				case "after": if (i > 0) prev.push(list1[orderItem.index]);
				case "before": {
					const newPrev = [...prev, currentItem];
					if (!nextItems.length) results.push([...newPrev, ...appendRemaining(queue.slice(i + 1))]);
					else results.push(...next(newPrev, nextItems, queue.slice(i)));
					break;
				}
				case "merge": {
					const merged = merge(list1[orderItem.index], currentItem);
					if (merged) {
						const newPrev = [...prev, merged];
						if (!nextItems.length) results.push([...newPrev, ...appendRemaining(queue.slice(i + 1))]);
						else results.push(...next(newPrev, nextItems, queue.slice(i + 1)));
					}
				}
			}
		}
		return results;
	}
	return next([], list2, getMergeOrders(list1.length));
}
/**
* Merge multiple arrays
*/
function mergeMultipleArrays(lists, merge) {
	if (!lists.length) return [];
	let prevLists = [lists[0]];
	for (let i = 1; i < lists.length; i++) {
		const mergeWith = lists[i];
		const newLists = [];
		for (const prevList of prevLists) newLists.push(...mergeArrays(prevList, mergeWith, merge));
		prevLists = newLists;
	}
	return prevLists;
}
export { mergeArrays, mergeMultipleArrays };
