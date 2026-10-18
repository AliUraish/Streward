# Original plant-room environment

This is a procedural, navigable 3D environment built with Three.js, React Three Fiber, and Drei. It does **not** contain the unavailable original reference scan. Geometry and generated concrete textures are local; no remote 3D assets or texture downloads are needed.

## Public components

`PlantRoom` fills its parent. Its props are documented in `API-CONTRACT.md` and exported as `PlantRoomProps` in `index.tsx`. All scene assets use the immutable IDs and anchor coordinates supplied through `components` from `shared/scene.json`.

- `selectedId` highlights geometry and the marker; `onSelect` fires from geometry or a marker.
- `cameraTarget` focuses the camera on an equipment ID. `reset-N` resets the view when `N` changes. Selection alone does not automatically move the camera.
- `showMarkers` toggles clickable world status markers. Marker colors and labels reflect backend component state.
- `showGuides` draws pump service-clearance guides.
- `viewMode` chooses orbit or walk. Walk uses W/A/S/D or arrows, Q/E vertically, Shift for faster movement, and drag to look. Keyboard input is scoped to the focused canvas.
- Optional `showControls={false}` hides internal helper controls when the parent supplies its own workspace controls.
- Room boundaries constrain walk navigation; this is an inspection viewer, not a collision or building-code simulation.

The viewer uses a demand render loop: camera changes, held navigation keys, and prop changes redraw the scene; a stationary view does not render continuously.

World markers are ordinary DOM elements owned by the application's React root. A lightweight projection bridge positions them from world coordinates on rendered frames, including behind-camera clipping. There are no independent React roots per marker, avoiding React 19 synchronous nested-root cleanup warnings during resize, Strict Mode remount, and view changes.

`CameraWall({ components, onSelect, running })` renders twelve fixed inspection stations from the same geometry, through one temporary render target in one canvas. Cards show **actual rendered model snapshots**, not live physical cameras. Station indicators reflect component state; the analyzing badge appears only when the parent reports a running backend job. A geometry signature prevents status polls from rerendering every snapshot. Click a card or a map station to select its linked asset; expand a card to inspect its snapshot.

## Validation

`npm --prefix frontend run typecheck` passes. Final browser visual/interaction checks are carried out with the complete application running locally.
