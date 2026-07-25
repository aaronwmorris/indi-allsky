/**
* Change ID in a string
*/
function changeIDInString(value, oldID, newID) {
	const escapedID = oldID.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
	return value.replace(new RegExp("([#;\"])(" + escapedID + ")([\")]|\\.[a-z])", "g"), "$1" + newID + "$3");
}
export { changeIDInString };
