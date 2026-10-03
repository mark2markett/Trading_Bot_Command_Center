import { Route, Routes } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { Header } from '../components/ui'
import { FleetPage } from './FleetPage'
import { BotPage } from './BotPage'
import { BotsPage } from './BotsPage'
import { RiskPage } from './RiskPage'
import { JournalPage, ResearchPage } from './Stubs'

export function App() {
  const fleet = useQuery({ queryKey: ['fleet'], queryFn: api.fleet, refetchInterval: 15000 })
  const stale = !!fleet.dataUpdatedAt && Date.now() - fleet.dataUpdatedAt > 60000 && fleet.isError
  return (
    <>
      <Header fleet={fleet.data ?? null} stale={stale || (!!fleet.data && Date.now() - fleet.dataUpdatedAt > 60000)} />
      <Routes>
        <Route path="/" element={fleet.data ? <FleetPage f={fleet.data} refetch={() => fleet.refetch()} /> : <main><div className="empty">{fleet.error ? <span className="neg">Server unreachable: {String(fleet.error)}</span> : 'Loading…'}</div></main>} />
        <Route path="/bots" element={<BotsPage />} />
        <Route path="/bots/:id" element={<BotPage />} />
        <Route path="/risk" element={<RiskPage />} />
        <Route path="/journal" element={<JournalPage />} />
        <Route path="/research" element={<ResearchPage />} />
      </Routes>
    </>
  )
}
