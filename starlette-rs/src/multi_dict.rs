//! Rust-native ordered multi-dictionaries.
//!
//! A multi-dictionary retains every input pair while mapping-style lookup
//! returns the last value for a key. Distinct-key views retain the order in
//! which keys first entered the underlying mapping, matching Python dict
//! insertion order.

/// Ordered key/value pairs with last-value mapping semantics.
#[derive(Clone, Debug)]
pub struct MultiDict<K, V> {
    keys: Vec<K>,
    items: Vec<(K, V)>,
}

impl<K, V> Default for MultiDict<K, V> {
    fn default() -> Self {
        Self {
            keys: Vec::new(),
            items: Vec::new(),
        }
    }
}

impl<K, V> MultiDict<K, V>
where
    K: Eq + Clone,
    V: Clone,
{
    /// Creates a multi-dictionary from ordered key/value pairs.
    #[must_use]
    pub fn from_pairs(items: impl IntoIterator<Item = (K, V)>) -> Self {
        let mut result = Self::default();
        for (key, value) in items {
            if !result.contains_key(&key) {
                result.keys.push(key.clone());
            }
            result.items.push((key, value));
        }
        result
    }

    /// Returns the last value associated with `key`.
    #[must_use]
    pub fn get(&self, key: &K) -> Option<&V> {
        self.items
            .iter()
            .rev()
            .find(|(item_key, _)| item_key == key)
            .map(|(_, value)| value)
    }

    /// Returns every value associated with `key`, in pair order.
    #[must_use]
    pub fn get_list(&self, key: &K) -> Vec<&V> {
        self.items
            .iter()
            .filter(|(item_key, _)| item_key == key)
            .map(|(_, value)| value)
            .collect()
    }

    /// Returns every input pair, including duplicate keys.
    #[must_use]
    pub fn multi_items(&self) -> &[(K, V)] {
        &self.items
    }

    /// Returns distinct keys in mapping insertion order.
    #[must_use]
    pub fn keys(&self) -> &[K] {
        &self.keys
    }

    /// Returns the final value for each key in mapping insertion order.
    #[must_use]
    pub fn values(&self) -> Vec<&V> {
        self.keys.iter().filter_map(|key| self.get(key)).collect()
    }

    /// Returns one final-value pair per key in mapping insertion order.
    #[must_use]
    pub fn items(&self) -> Vec<(&K, &V)> {
        self.keys
            .iter()
            .filter_map(|key| self.get(key).map(|value| (key, value)))
            .collect()
    }

    /// Returns the number of distinct keys.
    #[must_use]
    pub fn len(&self) -> usize {
        self.keys.len()
    }

    /// Returns whether the multi-dictionary has no pairs.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }

    /// Returns whether `key` is present.
    #[must_use]
    pub fn contains_key(&self, key: &K) -> bool {
        self.keys.iter().any(|item_key| item_key == key)
    }

    /// Replaces all occurrences of `key` with one value.
    pub fn set(&mut self, key: K, value: V) {
        self.set_list(key, [value]);
    }

    /// Removes all occurrences of `key` and returns its final value.
    pub fn pop(&mut self, key: &K) -> Option<V> {
        let value = self.get(key).cloned();
        if value.is_some() {
            self.remove_key(key);
        }
        value
    }

    /// Removes and returns the most recently inserted distinct key and value.
    pub fn pop_item(&mut self) -> Option<(K, V)> {
        let key = self.keys.pop()?;
        let value = self
            .items
            .iter()
            .rev()
            .find(|(item_key, _)| item_key == &key)
            .map(|(_, value)| value.clone());
        self.items.retain(|(item_key, _)| item_key != &key);
        value.map(|value| (key, value))
    }

    /// Removes all values for `key` and returns them in pair order.
    pub fn pop_list(&mut self, key: &K) -> Vec<V> {
        let values = self.get_list(key).into_iter().cloned().collect();
        self.remove_key(key);
        values
    }

    /// Removes every key and pair.
    pub fn clear(&mut self) {
        self.keys.clear();
        self.items.clear();
    }

    /// Returns the existing final value or inserts and returns `default`.
    pub fn set_default(&mut self, key: K, default: V) -> V {
        if let Some(value) = self.get(&key) {
            return value.clone();
        }
        self.keys.push(key.clone());
        self.items.push((key, default.clone()));
        default
    }

    /// Replaces all values for `key`, appending replacements in pair order.
    pub fn set_list(&mut self, key: K, values: impl IntoIterator<Item = V>) {
        let values = values.into_iter().collect::<Vec<_>>();
        if values.is_empty() {
            self.remove_key(&key);
            return;
        }
        if !self.contains_key(&key) {
            self.keys.push(key.clone());
        }
        self.items.retain(|(item_key, _)| item_key != &key);
        self.items
            .extend(values.into_iter().map(|value| (key.clone(), value)));
    }

    /// Appends a pair and updates mapping lookup to its value.
    pub fn append(&mut self, key: K, value: V) {
        if !self.contains_key(&key) {
            self.keys.push(key.clone());
        }
        self.items.push((key, value));
    }

    /// Applies another multi-dictionary's pairs using dict-style key ordering.
    pub fn update(&mut self, other: Self) {
        self.items.retain(|(key, _)| !other.contains_key(key));
        for key in &other.keys {
            if !self.contains_key(key) {
                self.keys.push(key.clone());
            }
        }
        self.items.extend(other.items);
    }

    fn remove_key(&mut self, key: &K) {
        self.keys.retain(|item_key| item_key != key);
        self.items.retain(|(item_key, _)| item_key != key);
    }
}

impl<K, V> MultiDict<K, V>
where
    K: Eq + Clone,
    V: Clone + PartialEq,
{
    /// Compares the duplicate-preserving pairs without depending on pair order.
    #[must_use]
    pub fn unordered_eq(&self, other: &Self) -> bool {
        self.items.len() == other.items.len()
            && self.items.iter().all(|item| {
                self.items
                    .iter()
                    .filter(|candidate| *candidate == item)
                    .count()
                    == other
                        .items
                        .iter()
                        .filter(|candidate| *candidate == item)
                        .count()
            })
    }
}
