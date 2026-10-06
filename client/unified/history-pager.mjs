/** Ordered server pages, with stale requests isolated from current selection. */
export function createHistoryPager(fetchPage) {
  let generation = 0;
  let page = {events: [], hasMore: false, before: null, loading: false, context: null};
  async function next() {
    if (page.loading || !page.hasMore) return false;
    const token = generation, current = page;
    current.loading = true;
    const params = new URLSearchParams({human_id: current.context.person, limit: '50',
      before: String(current.before), search: current.context.search || '', category: current.context.category || 'all'});
    try {
      const result = await fetchPage('/runs/' + encodeURIComponent(current.context.world) + '/history?' + params);
      if (token !== generation) return false;
      if (!Array.isArray(result.events)) throw Error('Invalid saved history page.');
      if (result.has_more && (!Number.isInteger(result.next_before) || result.next_before >= current.before))
        throw Error('Saved history cursor did not advance.');
      const known = new Set(current.events.map(event => event.event_id));
      for (const event of result.events) if (!known.has(event.event_id)) {
        known.add(event.event_id); current.events.push(event);
      }
      current.events.sort((a,b) => b.event_index - a.event_index);
      current.before = result.next_before;
      current.hasMore = Boolean(result.has_more);
      return true;
    } catch (error) {
      if (token !== generation) return false;
      throw error;
    } finally {
      current.loading = false;
    }
  }
  return {
    get events() { return page.events; },
    get hasMore() { return page.hasMore; },
    get loading() { return page.loading; },
    async reset(context) {
      ++generation;
      page = {events: [], hasMore: true, before: context.throughVersion, loading: false, context: {...context}};
      return next();
    },
    next,
    invalidate() { ++generation; page = {events: [], hasMore: false, before: null, loading: false, context: null}; }
  };
}
