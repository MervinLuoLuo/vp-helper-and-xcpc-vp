/**
 * Exposes the submissions a running `vp` terminal publishes for this VP.
 *
 * The terminal cannot open a BroadcastChannel, so it writes one small JSON file
 * and the page polls this endpoint. Absent or unreadable state simply means no
 * mirror is running, which must never break the page.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');

function stateFile() {
  if (process.env.VP_XCPC_STATE) return process.env.VP_XCPC_STATE;
  const root = process.env.XDG_STATE_HOME || path.join(os.homedir(), '.local', 'state');
  return path.join(root, 'vp', 'xcpc-vp.json');
}

module.exports = function vpXcpcFeed() {
  return {
    name: 'vp-xcpc-feed',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url?.split('?')[0] !== '/api/vp-xcpc') return next();
        res.setHeader('Content-Type', 'application/json');
        res.setHeader('Cache-Control', 'no-store');
        try {
          res.end(fs.readFileSync(stateFile(), 'utf8'));
        } catch {
          res.end('{}');
        }
      });
    },
  };
};
