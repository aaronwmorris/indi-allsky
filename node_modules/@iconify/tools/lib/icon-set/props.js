import { defaultIconProps } from "@iconify/utils";
import { commonObjectProps, unmergeObjects } from "@iconify/utils/lib/misc/objects";

/**
* Common properties for icon and alias
*/
const defaultCommonProps = Object.freeze({
	...defaultIconProps,
	hidden: false
});
/**
* Filter icon props: copies properties, removing undefined and default entries
*/
function filterProps(data, reference, compareDefaultValues) {
	const result = commonObjectProps(data, reference);
	return compareDefaultValues ? unmergeObjects(result, reference) : result;
}

export { defaultCommonProps, filterProps };