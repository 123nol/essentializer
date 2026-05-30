!(import! &self ../../petta_chainer)

!(import! &self ../metamath_axioms)

; === PeTTaChainer Script for Goal 0 ===
!(compileadd kb (: local-hyp-43d77088-0 (v0) (STV 1.0 1.0)))
!(compileadd kb (: local-hyp-43d77088-1 (v1) (STV 1.0 1.0)))
!(query 10 kb (: $prf (v1) $tv))

; --- Cleanup ---
;; cleanup needed
;; cleanup needed

; === PeTTaChainer Script for Goal 1 ===
!(compileadd kb (: local-hyp-42fa7d58-0 (v0) (STV 1.0 1.0)))
!(compileadd kb (: local-hyp-42fa7d58-1 (v1) (STV 1.0 1.0)))
!(query 10 kb (: $prf (v0) $tv))

; --- Cleanup ---
;; cleanup needed
;; cleanup needed