import React, { useState, useEffect, useRef, RefObject } from "react";
import { Outlet, NavLink, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import styles from "./Layout.module.css";

import { LoginButton } from "../../components/LoginButton";
import { IconButton } from "@fluentui/react";
import { getTokenForP4Ai, P4AiAuthSetup, logoutP4Ai } from "../../authConfig";
import { getApiToken, setApiToken } from "../../p4ai/auth";

const Layout = () => {
    const { t } = useTranslation();
    const [menuOpen, setMenuOpen] = useState(false);
    const menuRef: RefObject<HTMLDivElement> = useRef(null);
    const [Token, setToken] = useState<string | null>(null);
    const [name, setName] = useState<string>("");

    const toggleMenu = () => {
        setMenuOpen(!menuOpen);
    };

    const handleClickOutside = (event: MouseEvent) => {
        if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
            setMenuOpen(false);
        }
    };

    useEffect(() => {
        if (menuOpen) {
            document.addEventListener("mousedown", handleClickOutside);
        } else {
            document.removeEventListener("mousedown", handleClickOutside);
        }
        return () => {
            document.removeEventListener("mousedown", handleClickOutside);
        };
    }, [menuOpen]);

    const handleLogin = async () => {
        const scopes = ["ProtectionScopes.Compute.User", "SensitivityLabel.Read", "ContentActivity.Write", "User.Read", "Content.Process.User"];
        const response = await getTokenForP4Ai(scopes);
        if (!response) {
            throw new Error("Failed to obtain P4Ai access token.");
        }
        setApiToken(response.token);
        setToken(response.token);
        setName(response.name || "User");
    };

    const handleLogout = () => {
        logoutP4Ai();
        setApiToken("");
        sessionStorage.clear();
        setToken(null);
        setName("");
        window.location.reload();
    };

    return (
        <div className={styles.layout}>
            <header className={styles.header} role={"banner"}>
                <div className={styles.headerContainer} ref={menuRef}>
                    <Link to="/" className={styles.headerTitleContainer}>
                        <h3 className={styles.headerTitle}>{t("headerTitle")}</h3>
                    </Link>
                    <nav>
                        <ul className={`${styles.headerNavList} ${menuOpen ? styles.show : ""}`}>
                            <li>
                                <NavLink
                                    to="/"
                                    className={({ isActive }) => (isActive ? styles.headerNavPageLinkActive : styles.headerNavPageLink)}
                                    onClick={() => setMenuOpen(false)}
                                >
                                    {t("chat")}
                                </NavLink>
                            </li>
                            <li>
                                <NavLink
                                    to="/qa"
                                    className={({ isActive }) => (isActive ? styles.headerNavPageLinkActive : styles.headerNavPageLink)}
                                    onClick={() => setMenuOpen(false)}
                                >
                                    {t("qa")}
                                </NavLink>
                            </li>
                        </ul>
                    </nav>
                    <div className={styles.loginMenuContainer}>
                        {Token && name !== "" ? (
                            <div className={styles.headerNavPageLinkActive}>Welcome, {name}</div>
                        ) : (
                            <div className={styles.headerNavPageLinkActive}>Hello, Please Login to Continue</div>
                        )}
                        <button onClick={Token ? handleLogout : handleLogin} className={styles.loginButton}>
                            {Token ? "Logout" : "Login"}
                        </button>
                    </div>
                </div>
            </header>

            <main className={!Token ? styles.disabledContent : ""}>
                <Outlet />
            </main>
        </div>
    );
};

export default Layout;
