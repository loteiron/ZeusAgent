import { useStore } from '@nanostores/react'
import { useEffect } from 'react'

import Failure from './routes/failure'
import Progress from './routes/progress'
import Success from './routes/success'
import Welcome from './routes/welcome'
import { $bootstrap, $route, initialize } from './store'

/** The framed setup workspace contains all four existing installation states. */
export default function App() {
  const route = useStore($route)
  const bootstrap = useStore($bootstrap)

  useEffect(() => {
    void initialize()
  }, [])

  return (
    <div className="relative flex h-full flex-col overflow-hidden bg-background p-4 text-foreground">
      <main className="installer-panel relative z-10 flex flex-1 flex-col overflow-hidden">
        {route === 'welcome' && <Welcome />}
        {route === 'progress' && <Progress bootstrap={bootstrap} />}
        {route === 'success' && <Success />}
        {route === 'failure' && <Failure bootstrap={bootstrap} />}
      </main>
    </div>
  )
}
