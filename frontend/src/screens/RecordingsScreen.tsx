import RecordingsLibrary from '../components/RecordingsLibrary'

function RecordingsScreen() {
  return (
    <main className="game-screen">
      <section className="panel">
        <h1>My recordings</h1>
        <RecordingsLibrary />
      </section>
    </main>
  )
}

export default RecordingsScreen
