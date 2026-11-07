/* Pure tests of the actual passive Square hit helpers; no game/bridge mocks. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "inspect-ui.js"), "utf8");
const start = source.indexOf("    function squareLocalVertices(");
const end = source.indexOf("    function inspect(expectedThread)", start);
assert(start > 0 && end > start, "Actual Square helper block is required");
const context = {};
vm.runInNewContext(source.slice(start, end) +
    "\nglobalThis.api = {squareLocalVertices, strictQuadrilateralContains, selectSquareHitCandidate};",
    context, {timeout: 1000});
const {squareLocalVertices: build, strictQuadrilateralContains: contains, selectSquareHitCandidate: select} = context.api;
const plain = value => JSON.parse(JSON.stringify(value));
const corners = [[0, 0, 0], [0, 100, 0], [100, 100, 0], [100, 0, 0]];
const xy = values => values.map(v => v.slice(0, 2));
const diamond = xy(build(corners, 0.5));
let count = 0;
function check(name, body) { body(); count++; }
check("native pivot-half edge order creates diamond", () => assert.deepEqual(plain(diamond), [[0, 50], [50, 100], [100, 50], [50, 0]]));
check("negative pivot clamps to first edge endpoints", () => assert.deepEqual(plain(build(corners, -2)), corners));
check("large pivot clamps to second edge endpoints", () => assert.deepEqual(plain(build(corners, 3)), [corners[1], corners[2], corners[3], corners[0]]));
check("all axes interpolate without changing inputs", () => {
    const before = JSON.stringify(corners); const actual = build([[0, 0, 2], [0, 4, 6], [4, 4, 10], [4, 0, 14]], 0.25);
    assert.deepEqual(plain(actual), [[0, 1, 3], [1, 4, 7], [4, 3, 11], [3, 0, 11]]); assert.equal(JSON.stringify(corners), before);
});
check("invalid pivot refuses", () => { for (const value of [NaN, Infinity, -Infinity, "0.5", null]) assert.equal(build(corners, value), null); });
check("wrong corner count refuses", () => { assert.equal(build(corners.slice(0, 3), 0.5), null); assert.equal(build(null, 0.5), null); });
check("invalid corner vectors refuse", () => {
    assert.equal(build([[0, 0], ...corners.slice(1)], 0.5), null);
    assert.equal(build([[NaN, 0, 0], ...corners.slice(1)], 0.5), null);
});
check("internal native triangle diagonal is accepted", () => assert.equal(contains(diamond, [50, 50]), true));
check("full rectangle corner outside diamond refuses", () => assert.equal(contains(diamond, [5, 5]), false));
check("outer edge and vertex refuse", () => { assert.equal(contains(diamond, [25, 25]), false); assert.equal(contains(diamond, [0, 50]), false); });
check("quarter-pixel edge margin refuses numerical near-edge", () => {
    const rectangle = xy(build(corners, 0)); assert.equal(contains(rectangle, [0.249, 50]), false); assert.equal(contains(rectangle, [0.251, 50]), true);
});
check("both windings accepted", () => assert.equal(contains([...diamond].reverse(), [50, 50]), true));
check("outside point refuses", () => assert.equal(contains(diamond, [101, 50]), false));
check("nonfinite point refuses", () => { assert.equal(contains(diamond, [Infinity, 50]), false); assert.equal(contains(diamond, [50]), false); });
check("nonfinite vertex refuses", () => assert.equal(contains([[Infinity, 50], ...diamond.slice(1)], [50, 50]), false));
check("duplicate vertices refuse", () => assert.equal(contains([[0, 0], [0, 0], [10, 10], [10, 0]], [3, 3]), false));
check("collinear vertices refuse", () => assert.equal(contains([[0, 0], [1, 0], [2, 0], [3, 0]], [1, 0]), false));
check("concave quad refuses", () => assert.equal(contains([[0, 0], [0, 100], [20, 20], [100, 0]], [15, 15]), false));
check("self intersecting quad refuses", () => assert.equal(contains([[0, 0], [100, 100], [0, 100], [100, 0]], [50, 50]), false));
check("rounded centroid selects integer native-diagonal point", () => {
    const hit = select(diamond, [0, 0, 100, 100], [0, 0, 1280, 720]); assert.deepEqual(plain(hit.point), [50, 50]); assert.equal(hit.source, "projected-quadrilateral-centroid-rounded");
});
check("affine rotated skewed projection preserves actual quad", () => {
    const projected = diamond.map(([x, y]) => [200 + 1.5 * x + 0.2 * y, 200 - 0.3 * x + 0.7 * y]);
    const hit = select(projected, [190, 160, 400, 300], [0, 0, 1280, 720]); assert(hit); assert(contains(projected, hit.point));
});
check("noninteger centroid validated after rounding", () => {
    const shifted = diamond.map(([x, y]) => [x + 0.37, y + 0.41]);
    const hit = select(shifted, [0, 0, 101, 101], [0, 0, 1280, 720]); assert.deepEqual(plain(hit.point), [50, 50]); assert(contains(shifted, hit.point));
});
check("zero or malformed bounds refuse", () => {
    for (const bounds of [[0, 0, 0, 10], [0, 0, NaN, 100], [0, 0, 100], null]) assert.equal(select(diamond, bounds, [0, 0, 1280, 720]), null);
});
check("candidate clipped by measured bounds refuses", () => assert.equal(select(diamond, [0, 0, 10, 10], [0, 0, 1280, 720]), null));
check("candidate outside current game view refuses", () => assert.equal(select(diamond, [0, 0, 100, 100], [60, 60, 1280, 720]), null));
check("no strictly interior integer pixel refuses", () => {
    const small = [[0, 0.49], [0.49, 0.98], [0.98, 0.49], [0.49, 0]];
    assert.equal(select(small, [0, 0, 0.98, 0.98], [0, 0, 1280, 720]), null);
});
check("invalid quad never falls back to rectangle center", () => assert.equal(select([[0, 0], [100, 100], [0, 100], [100, 0]], [0, 0, 100, 100], [0, 0, 1280, 720]), null));
console.log(JSON.stringify({status: "PASS", cases: count, scope: "Actual source pure Square helpers only; no runtime raycast or device evidence"}));
